"""
agents/alpha_combination_agent.py — Pondération dynamique IC-based (Fundamental Law)

Implémente une version simplifiée de l'alpha combination engine (Grinold & Kahn) :

    IR = IC × √N_eff

Pour chaque agent :
  1. Calcule l'IC (Information Coefficient) = corrélation entre le score centré
     et le signe du résultat réel sur l'historique des trades évalués.
  2. Détecte les agents corrélés entre eux (réduction de N_eff, pénalité).
  3. Retourne des poids optimaux : w(i) ∝ IC(i) / σ(i) × décote_corrélation.

Les poids produits remplacent les poids statiques weight_in_scoring du yaml.
Si désactivé ou si l'historique est insuffisant, le ScoreCalculator utilise
ses poids statiques habituels — aucune régression possible.

Activation via settings.yaml :
    agents:
      alpha_combination:
        enabled: false           # mettre true pour activer
        min_history: 20          # min trades évalués (result_24h non NULL)
        lookback_days: 90        # fenêtre glissante en jours
        correlation_threshold: 0.70  # corrélation max tolérée entre agents
        ic_floor: 0.0            # IC minimal pour recevoir un poids > 0
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("zeitgeist.alpha_combination")


class AlphaCombinationAgent:
    """
    Calcule des poids d'agents basés sur leur IC historique.

    Usage :
        agent = AlphaCombinationAgent()
        weights = agent.run(asset="BTC/USDT")
        # -> {"market_data": 0.42, "fear_greed": 0.08, ...} ou None
    """

    def __init__(self):
        from utils.config import load_settings
        cfg = load_settings()
        ac_cfg = cfg.get("agents", {}).get("alpha_combination", {})
        self.enabled: bool = bool(ac_cfg.get("enabled", False))
        self.min_history: int = int(ac_cfg.get("min_history", 20))
        self.lookback_days: int = int(ac_cfg.get("lookback_days", 90))
        self.correlation_threshold: float = float(ac_cfg.get("correlation_threshold", 0.70))
        self.ic_floor: float = float(ac_cfg.get("ic_floor", 0.0))

    def run(self, asset: str | None = None) -> Optional[dict[str, float]]:
        """
        Retourne un dict normalisé {agent_name: weight} ou None si inactif / données insuffisantes.

        Returns None quand :
          - enabled = false
          - moins de min_history trades évalués
          - erreur inattendue (fallback silencieux sur poids statiques)
        """
        if not self.enabled:
            return None

        try:
            records = self._load_history(asset)
            if len(records) < self.min_history:
                logger.info(
                    f"AlphaCombination: {len(records)} trades évalués "
                    f"< min={self.min_history} — poids statiques conservés"
                )
                return None

            ic_per_agent = self._compute_ic(records)
            if not ic_per_agent:
                logger.info("AlphaCombination: aucun IC calculable — poids statiques conservés")
                return None

            corr_matrix = self._compute_correlation_matrix(records)
            weights = self._compute_optimal_weights(ic_per_agent, corr_matrix, records)

            if not weights:
                return None

            _ic_str = ", ".join(f"{k}:{v:+.3f}" for k, v in sorted(ic_per_agent.items()))
            _w_str  = ", ".join(f"{k}:{v:.3f}"  for k, v in sorted(weights.items()))
            logger.info(
                f"AlphaCombination: {len(records)} trades sur {self.lookback_days}j | "
                f"IC=[{_ic_str}] | weights=[{_w_str}]"
            )
            return weights

        except Exception as exc:
            logger.warning(
                f"AlphaCombination: erreur calcul ({exc}) — poids statiques conservés",
                exc_info=True,
            )
            return None

    # ------------------------------------------------------------------
    # Chargement historique
    # ------------------------------------------------------------------

    def _load_history(self, asset: str | None) -> list[dict]:
        """
        Charge les décisions évaluées (result_24h non NULL) avec leurs scores par agent.
        Retourne une liste de dicts : {agent_scores: {str: float}, result_24h: float, action: str}
        """
        import json as _json
        from storage.database import get_connection

        cutoff = (datetime.utcnow() - timedelta(days=self.lookback_days)).isoformat()

        with get_connection() as conn:
            if asset:
                rows = conn.execute(
                    """
                    SELECT weights_snapshot, result_24h, action
                    FROM decisions
                    WHERE asset = ?
                      AND result_24h IS NOT NULL
                      AND weights_snapshot IS NOT NULL
                      AND datetime(timestamp) >= datetime(?)
                    ORDER BY timestamp ASC
                    """,
                    (asset, cutoff),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT weights_snapshot, result_24h, action
                    FROM decisions
                    WHERE result_24h IS NOT NULL
                      AND weights_snapshot IS NOT NULL
                      AND datetime(timestamp) >= datetime(?)
                    ORDER BY timestamp ASC
                    LIMIT 2000
                    """,
                    (cutoff,),
                ).fetchall()

        records = []
        for row in rows:
            try:
                ws = _json.loads(row["weights_snapshot"] or "{}")
                # agent_scores stocké dans score_breakdown.agents.detail
                breakdown = ws
                agent_scores = (
                    breakdown.get("agents", {}).get("detail")
                    or breakdown.get("agent_scores")
                    or {}
                )
                if not agent_scores:
                    continue
                records.append({
                    "agent_scores": {k: float(v) for k, v in agent_scores.items()},
                    "result_24h": float(row["result_24h"]),
                    "action": row["action"],
                })
            except Exception:
                continue

        return records

    # ------------------------------------------------------------------
    # IC par agent
    # ------------------------------------------------------------------

    def _compute_ic(self, records: list[dict]) -> dict[str, float]:
        """
        IC(agent) = corrélation de Pearson entre :
          - série centrée du score agent  (score - 50)
          - signe du résultat réel        (+1 si result_24h > 0, -1 sinon)

        Un IC > 0 signifie que le score prédit correctement la direction.
        Un IC < 0 signifie un signal systématiquement inversé (ex. fear_greed historique).
        """
        n = len(records)

        # Séries brutes
        agent_series: dict[str, list[float]] = {}
        outcome_series: list[float] = []

        for rec in records:
            outcome_series.append(1.0 if rec["result_24h"] > 0 else -1.0)
            for agent, score in rec["agent_scores"].items():
                agent_series.setdefault(agent, []).append(float(score) - 50.0)

        ic: dict[str, float] = {}
        for agent, series in agent_series.items():
            # Tolérance 20% données manquantes : compléter par 0.0
            if len(series) < n * 0.5:
                continue
            if len(series) < n:
                series = series + [0.0] * (n - len(series))

            pearson = _pearson(series, outcome_series[:len(series)])
            ic[agent] = round(pearson, 4)

        return ic

    # ------------------------------------------------------------------
    # Matrice de corrélation inter-agents
    # ------------------------------------------------------------------

    def _compute_correlation_matrix(
        self, records: list[dict]
    ) -> dict[str, dict[str, float]]:
        """Corrélation de Pearson entre les séries de scores centrés de chaque paire d'agents."""
        agents = sorted({a for rec in records for a in rec["agent_scores"]})

        series: dict[str, list[float]] = {a: [] for a in agents}
        for rec in records:
            for agent in agents:
                score = rec["agent_scores"].get(agent, 50.0)
                series[agent].append(float(score) - 50.0)

        corr: dict[str, dict[str, float]] = {}
        for a in agents:
            corr[a] = {}
            for b in agents:
                corr[a][b] = 1.0 if a == b else _pearson(series[a], series[b])

        return corr

    # ------------------------------------------------------------------
    # Calcul des poids optimaux
    # ------------------------------------------------------------------

    def _compute_optimal_weights(
        self,
        ic: dict[str, float],
        corr_matrix: dict[str, dict[str, float]],
        records: list[dict],
    ) -> dict[str, float]:
        """
        w(i) = max(0, IC(i)) / σ(i) × (1 - avg_|corr| avec les autres actifs positifs)

        Normalisé tel que Σw = 1.0.
        Les agents avec IC ≤ ic_floor reçoivent un poids nul.
        """
        # Séries centrées pour calculer σ
        agent_series: dict[str, list[float]] = {}
        for rec in records:
            for agent, score in rec["agent_scores"].items():
                agent_series.setdefault(agent, []).append(float(score) - 50.0)

        positive_agents = [a for a, v in ic.items() if v > self.ic_floor]

        weights_raw: dict[str, float] = {}
        for agent, agent_ic in ic.items():
            if agent_ic <= self.ic_floor:
                weights_raw[agent] = 0.0
                continue

            series = agent_series.get(agent, [])
            if not series:
                weights_raw[agent] = 0.0
                continue

            mean_ = sum(series) / len(series)
            variance = sum((x - mean_) ** 2 for x in series) / len(series)
            std = math.sqrt(variance) if variance > 0 else 1.0

            # Décote corrélation : plus un agent est corrélé aux autres,
            # moins il apporte d'information indépendante (N_eff ↓)
            peers = [a for a in positive_agents if a != agent]
            if peers:
                avg_abs_corr = sum(
                    abs(corr_matrix.get(agent, {}).get(p, 0.0)) for p in peers
                ) / len(peers)
                decorrelation = max(0.1, 1.0 - avg_abs_corr)
            else:
                decorrelation = 1.0

            weights_raw[agent] = (agent_ic / std) * decorrelation

        total = sum(v for v in weights_raw.values() if v > 0)
        if total <= 0:
            return {}

        return {
            agent: round(w / total, 4)
            for agent, w in weights_raw.items()
            if w > 0
        }


# ------------------------------------------------------------------
# Helpers statistiques (sans dépendance numpy)
# ------------------------------------------------------------------

def _pearson(x: list[float], y: list[float]) -> float:
    """Corrélation de Pearson — implémentation pure Python."""
    n = min(len(x), len(y))
    if n < 3:
        return 0.0
    x, y = x[:n], y[:n]
    mx = sum(x) / n
    my = sum(y) / n
    cov = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    sx = math.sqrt(sum((xi - mx) ** 2 for xi in x))
    sy = math.sqrt(sum((yi - my) ** 2 for yi in y))
    if sx < 1e-10 or sy < 1e-10:
        return 0.0
    return cov / (sx * sy)
