"""
agents/post_mortem_agent.py — Analyse retrospective et ajustement des poids.

Ameliorations integrees :
  F6  — Calibration isotonique des scores (IsotonicRegression)
  F7  — Champion-Challenger : notification si un profil shadow surperforme
  F13 — Regression logistique sur fenetre glissante pour les poids optimaux
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger("zeitgeist.post_mortem")

_CALIBRATION_PATH = Path(__file__).resolve().parent.parent / "storage" / "calibration.json"
_PM_STATE_PATH    = Path(__file__).resolve().parent.parent / "storage" / "pm_state.json"


class PostMortemAgent:
    """
    Analyse les decisions passees, compare prediction vs resultat,
    et propose des ajustements de poids pour les prochains cycles.
    """

    def __init__(self):
        from utils.config import load_settings
        cfg = load_settings()
        pm = cfg.get("post_mortem", {})
        self.learning_rate: float = pm.get("learning_rate", 0.05)
        self.min_history: int = pm.get("min_history_for_adjustment", 10)
        self.weight_min: float = cfg.get("scoring", {}).get("min_weight", 0.05)
        self.weight_max: float = cfg.get("scoring", {}).get("max_weight", 0.60)
        self.walk_forward_days: int = int(pm.get("walk_forward_days", 7))
        self.correlation_threshold: float = float(
            pm.get("correlation_threshold", 0.75)
        )

    def run(self, pending_decisions: list[dict]) -> None:
        """
        Pour chaque decision en attente :
        1. Recupere le prix 24h plus tard
        2. Calcule le resultat reel
        3. Met a jour la DB
        4. Si assez d'historique, ajuste les poids + calibration + champion-challenger
        """
        from utils.logger import log_flux_metric

        logger.info(f"Post-mortem : analyse de {len(pending_decisions)} decisions")
        t0 = time.time()
        try:
            for decision in pending_decisions:
                self._process_single(decision)

            n_evaluated = len(pending_decisions)
            self._maybe_adjust_weights()
            self._maybe_adjust_individual_agent_weights()
            self._maybe_calibrate_scores()
            self._maybe_promote_champion()
            self._run_meta_analysis()

            # CA5: AtlasDream — consolidation mémorielle tous les N cycles évalués
            try:
                from storage.database import get_recent_decisions
                total_evaluated = len([
                    d for d in get_recent_decisions(1000)
                    if d.get("result_24h") is not None
                ])
                from agents.atlas_dream import AtlasDreamService
                AtlasDreamService().maybe_consolidate(total_evaluated)
            except Exception as dream_exc:
                logger.debug("[AtlasDream] Consolidation ignorée : %s", dream_exc)

            latency_ms = int((time.time() - t0) * 1000)
            log_flux_metric("post_mortem", "ok", latency_ms, len(pending_decisions))
        except Exception as exc:
            latency_ms = int((time.time() - t0) * 1000)
            log_flux_metric("post_mortem", "error", latency_ms, 0, str(exc))
            raise

    def _process_single(self, decision: dict) -> None:
        """Calcule le resultat reel d'une decision et l'enregistre."""
        from storage.database import update_decision_result
        try:
            cycle_id = decision["cycle_id"]
            action = decision.get("action", "HOLD")
            entry_price = decision.get("entry_price", 0) or 0

            if action == "HOLD" or entry_price == 0:
                update_decision_result(cycle_id, 0.0)
                return

            # SELL = signal de sortie, P&L déjà calculé sur la ligne BUY via close_position()
            # Ne pas réévaluer comme short fictif (système long-only spot)
            if action == "SELL":
                update_decision_result(cycle_id, 0.0)
                return

            current_price = self._get_current_price(decision.get("asset", "BTC/USDT"))
            position_size = decision.get("position_size", 0) or 0

            if current_price and entry_price:
                price_change_pct = (current_price - entry_price) / entry_price
                direction = 1 if action == "BUY" else -1
                pnl = position_size * price_change_pct * direction
            else:
                pnl = 0.0

            update_decision_result(cycle_id, round(pnl, 2))
            logger.info(
                f"Post-mortem {cycle_id}: {action} entry={entry_price:.2f} "
                f"current={current_price:.2f} P&L={pnl:.2f}$"
            )
        except Exception as exc:
            logger.error(f"Post-mortem error for decision {decision.get('cycle_id')}: {exc}")

    def _get_current_price(self, asset: str) -> float:
        """Recupere le prix actuel via CCXT."""
        try:
            from agents.market_data_agent import MarketDataAgent
            agent = MarketDataAgent()
            indicators = agent.get_indicators(asset)
            return indicators.get("price", 0)
        except Exception:
            return 0.0

    # ------------------------------------------------------------------
    # F13 — Regression logistique sur fenetre glissante
    # ------------------------------------------------------------------
    def _maybe_adjust_weights(self) -> None:
        """
        Ajuste les poids par regression logistique sur les N derniers cycles (F13).
        Walk-forward : n'exécute qu'une fois tous les walk_forward_days jours.
        Fallback sur ajustement win_rate linéaire si sklearn indisponible.
        """
        from storage.database import get_pnl_history
        from utils.config import load_settings, save_settings

        # Walk-forward : vérifier la fenêtre depuis le dernier ajustement
        if not self._walk_forward_due():
            return

        history = [h for h in get_pnl_history() if h.get("result_24h") is not None]
        if len(history) < self.min_history:
            logger.info(
                f"Post-mortem : {len(history)}/{self.min_history} decisions — "
                f"ajustement des poids reporte"
            )
            return

        recent = history[-max(self.min_history, 50):]
        wins = [h for h in recent if (h.get("result_24h") or 0) > 0]
        win_rate = len(wins) / len(recent)
        logger.info(f"Post-mortem : win_rate={win_rate:.0%} sur {len(recent)} decisions")

        # Vérification de la corrélation inter-agents avant ajustement
        self._agents_correlation_check(recent)

        # Tentative de regression logistique si sklearn disponible (F13)
        new_weights = self._compute_logistic_weights(recent)
        cfg = load_settings()
        weights = cfg.get("scoring", {}).get("weights", {})

        if new_weights:
            mf_new = new_weights.get("mirofish", weights.get("mirofish", 0.40))
            market_new = new_weights.get("market", weights.get("market", 0.30))
            agents_new = new_weights.get("agents", weights.get("agents", 0.20))
            contrarian_new = new_weights.get("contrarian", weights.get("contrarian", 0.10))
        else:
            # Fallback : ajustement win_rate lineaire (original)
            delta = (win_rate - 0.50) * self.learning_rate
            mf_new = weights.get("mirofish", 0.40) + delta
            market_new = weights.get("market", 0.30) - delta / 2
            agents_new = weights.get("agents", 0.20) - delta / 2
            contrarian_new = weights.get("contrarian", 0.10)

        # Borner les poids
        def clamp(v: float) -> float:
            return max(self.weight_min, min(self.weight_max, v))

        mf_new = clamp(mf_new)
        market_new = clamp(market_new)
        agents_new = clamp(agents_new)
        contrarian_new = clamp(contrarian_new)

        # Normaliser
        total = mf_new + market_new + agents_new + contrarian_new
        cfg["scoring"]["weights"] = {
            "mirofish": round(mf_new / total, 4),
            "market": round(market_new / total, 4),
            "agents": round(agents_new / total, 4),
            "contrarian": round(contrarian_new / total, 4),
        }
        save_settings(cfg)
        logger.info(
            f"Post-mortem : poids mis a jour -> "
            f"mirofish={mf_new/total:.3f} market={market_new/total:.3f} "
            f"agents={agents_new/total:.3f} contrarian={contrarian_new/total:.3f}"
        )
        self._persist_pm_state({"last_adjustment_at": time.time()})

    # ------------------------------------------------------------------
    # Auto-tune poids individuels par agent (weight_in_scoring)
    # ------------------------------------------------------------------
    def _maybe_adjust_individual_agent_weights(self) -> None:
        """
        Ajuste le weight_in_scoring de chaque agent individuel dans settings.yaml
        en fonction de son win_rate sur les 30 derniers jours.

        Règles :
        - win_rate ≥ 60% → +5% poids (récompense)
        - win_rate 50-60% → poids inchangé
        - win_rate < 50% → -10% poids (pénalité)
        - win_rate < 40% avec ≥ 20 signaux → désactiver (warning log)

        Walk-forward : ne s'exécute que si _maybe_adjust_weights() vient de tourner.
        """
        if not self._walk_forward_due():
            return

        try:
            from storage.database import get_agent_performance_stats
            from utils.config import load_settings, save_settings

            stats = get_agent_performance_stats(days=30)
            if not stats:
                return

            cfg = load_settings()
            agents_cfg = cfg.setdefault("agents", {})
            changed = False

            for s in stats:
                agent = s["agent"]
                wr = s["win_rate"]          # 0–100
                n  = s["signal_count"]
                if n < 15:
                    # Pas assez de données pour ajuster
                    continue

                agent_entry = agents_cfg.setdefault(agent, {})
                current_w = float(agent_entry.get("weight_in_scoring", 0.5))

                if wr >= 60:
                    new_w = min(0.95, current_w * 1.05)
                    logger.info(
                        f"[AutoTune] {agent}: win_rate={wr}% ≥ 60% "
                        f"→ poids {current_w:.3f} → {new_w:.3f} (+5%)"
                    )
                elif wr < 50:
                    new_w = max(0.05, current_w * 0.90)
                    logger.info(
                        f"[AutoTune] {agent}: win_rate={wr}% < 50% "
                        f"→ poids {current_w:.3f} → {new_w:.3f} (-10%)"
                    )
                    if wr < 40 and n >= 20:
                        logger.warning(
                            f"[AutoTune] {agent}: win_rate={wr}% < 40% sur {n} signaux "
                            f"— envisager de désactiver dans la config"
                        )
                else:
                    continue  # 50–60% : neutre, on ne touche pas

                agent_entry["weight_in_scoring"] = round(new_w, 4)
                changed = True

            if changed:
                save_settings(cfg)
                logger.info("[AutoTune] weight_in_scoring mis à jour dans settings.yaml")

        except Exception as exc:
            logger.warning(f"[AutoTune] Ajustement poids individuels échoué: {exc}")

    def _compute_logistic_weights(self, history: list[dict]) -> dict | None:
        """
        F13 — Regression logistique : quel facteur predit le mieux la direction reelle ?
        Retourne des poids normalises ou None si sklearn est indisponible.
        """
        try:
            import numpy as np
            from sklearn.linear_model import LogisticRegression

            rows = [
                h for h in history
                if (
                    h.get("mirofish_score") is not None
                    and h.get("market_score") is not None
                    and h.get("agents_mean") is not None
                    and h.get("contrarian_score") is not None
                    and h.get("result_24h") is not None
                )
            ]
            if len(rows) < 30:
                return None

            X = np.array([
                [
                    h["mirofish_score"],
                    h["market_score"],
                    h.get("agents_mean", 50),
                    h["contrarian_score"],
                ]
                for h in rows
            ])
            y = np.array([1 if h["result_24h"] > 0 else 0 for h in rows])

            # Regression logistique avec regularisation
            lr = LogisticRegression(C=1.0, max_iter=300, random_state=42)
            lr.fit(X, y)

            raw = dict(zip(
                ["mirofish", "market", "agents", "contrarian"],
                np.abs(lr.coef_[0]),
            ))
            total = sum(raw.values()) or 1.0
            normalized = {k: float(v / total) for k, v in raw.items()}
            logger.info(f"Post-mortem LogReg poids : {normalized}")
            return normalized
        except ImportError:
            logger.debug("sklearn non disponible — fallback win_rate lineaire")
            return None
        except Exception as exc:
            logger.warning(f"Regression logistique echouee: {exc}")
            return None

    # ------------------------------------------------------------------
    # Walk-forward helpers
    # ------------------------------------------------------------------

    def _walk_forward_due(self) -> bool:
        """Retourne True si walk_forward_days sont écoulés depuis le dernier ajustement."""
        state = self._load_pm_state()
        last = state.get("last_adjustment_at", 0.0)
        elapsed_days = (time.time() - float(last)) / 86_400
        due = elapsed_days >= self.walk_forward_days
        if not due:
            logger.info(
                f"Post-mortem walk-forward : prochain ajustement dans "
                f"{self.walk_forward_days - elapsed_days:.1f} jours"
            )
        return due

    @staticmethod
    def _load_pm_state() -> dict:
        try:
            if _PM_STATE_PATH.exists():
                return json.loads(_PM_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    @staticmethod
    def _persist_pm_state(updates: dict) -> None:
        try:
            state = PostMortemAgent._load_pm_state()
            state.update(updates)
            _PM_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _PM_STATE_PATH.write_text(
                json.dumps(state, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.debug(f"pm_state persist error: {exc}")

    # ------------------------------------------------------------------
    # Correlation check inter-agents
    # ------------------------------------------------------------------

    def _agents_correlation_check(self, recent: list[dict]) -> None:
        """
        Calcule la corrélation de Pearson entre les scores des agents
        sur les 30 derniers cycles. Si corr(A, B) > correlation_threshold,
        loggue un avertissement et réduit de 10% le poids de l'agent
        le moins performant entre les deux.
        """
        try:
            import numpy as np
            from utils.config import load_settings, save_settings

            # Colonnes disponibles dans l'historique
            agent_cols = ["mirofish_score", "market_score", "agents_mean", "contrarian_score"]
            col_map    = {
                "mirofish_score": "mirofish",
                "market_score":   "market",
                "agents_mean":    "agents",
                "contrarian_score": "contrarian",
            }

            window = recent[-30:]
            data = {col: [] for col in agent_cols}
            for row in window:
                for col in agent_cols:
                    v = row.get(col)
                    if v is not None:
                        data[col].append(float(v))

            # Ne garder que les colonnes avec assez de données
            valid = [c for c in agent_cols if len(data[c]) >= 20]
            if len(valid) < 2:
                return

            # Perf de chaque agent (win_rate sur les cycles concernés)
            def agent_win_rate(col: str) -> float:
                pairs = [
                    (row.get(col), row.get("result_24h"))
                    for row in window
                    if row.get(col) is not None and row.get("result_24h") is not None
                ]
                if not pairs:
                    return 0.0
                wins = sum(1 for s, r in pairs if (s > 50) == (r > 0))
                return wins / len(pairs)

            cfg = load_settings()
            weights = cfg.get("scoring", {}).get("weights", {})
            changed = False

            for i, col_a in enumerate(valid):
                for col_b in valid[i + 1:]:
                    min_len = min(len(data[col_a]), len(data[col_b]))
                    if min_len < 20:
                        continue
                    arr_a = np.array(data[col_a][-min_len:])
                    arr_b = np.array(data[col_b][-min_len:])
                    if np.std(arr_a) < 1e-9 or np.std(arr_b) < 1e-9:
                        continue
                    r = float(np.corrcoef(arr_a, arr_b)[0, 1])
                    if r > self.correlation_threshold:
                        wa_key = col_map[col_a]
                        wb_key = col_map[col_b]
                        wr_a = agent_win_rate(col_a)
                        wr_b = agent_win_rate(col_b)
                        weaker = wa_key if wr_a <= wr_b else wb_key
                        logger.warning(
                            f"Corrélation {wa_key}/{wb_key} = {r:.2f} > seuil "
                            f"{self.correlation_threshold} — réduction poids '{weaker}' de 10%"
                        )
                        if weaker in weights:
                            weights[weaker] = round(
                                max(self.weight_min, weights[weaker] * 0.90), 4
                            )
                            changed = True

            if changed:
                # Re-normaliser
                total = sum(weights.values()) or 1.0
                cfg["scoring"]["weights"] = {
                    k: round(v / total, 4) for k, v in weights.items()
                }
                save_settings(cfg)
                logger.info(f"Post-mortem : poids corrigés après check corrélation")

        except ImportError:
            logger.debug("numpy non disponible — correlation check ignoré")
        except Exception as exc:
            logger.warning(f"Correlation check error: {exc}")

    # ------------------------------------------------------------------
    # F6 — Calibration isotonique des scores
    # ------------------------------------------------------------------
    def _maybe_calibrate_scores(self) -> None:
        """
        F6 — Applique une regression isotonique sur les scores historiques
        pour produire un mapping score -> probabilite calibree.
        Stocke le mapping dans storage/calibration.json.
        """
        try:
            import numpy as np
            from sklearn.isotonic import IsotonicRegression
            from storage.database import get_pnl_history

            history = [
                h for h in get_pnl_history()
                if h.get("result_24h") is not None and h.get("score") is not None
            ]
            if len(history) < 30:
                return

            scores = np.array([float(h["score"]) for h in history])
            outcomes = np.array([1 if h["result_24h"] > 0 else 0 for h in history])

            ir = IsotonicRegression(out_of_bounds="clip")
            ir.fit(scores, outcomes)

            # Discretiser en 101 points [0..100]
            x_grid = np.arange(0, 101, 1, dtype=float)
            y_grid = ir.predict(x_grid)
            calibration_map = {int(x): round(float(y), 4) for x, y in zip(x_grid, y_grid)}

            _CALIBRATION_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(_CALIBRATION_PATH, "w", encoding="utf-8") as f:
                json.dump(
                    {"version": 1, "n_samples": len(history), "map": calibration_map},
                    f, indent=2
                )
            logger.info(
                f"Post-mortem : calibration isotonique mise a jour "
                f"({len(history)} echantillons)"
            )
        except ImportError:
            logger.debug("sklearn non disponible — calibration ignoree")
        except Exception as exc:
            logger.warning(f"Calibration isotonique echouee: {exc}")

    # ------------------------------------------------------------------
    # Méta-analyse LLM — patterns d'échec
    # ------------------------------------------------------------------

    def _meta_analysis_due(self) -> bool:
        """Retourne True si meta_analysis_interval_days sont écoulés depuis la dernière analyse."""
        from utils.config import load_settings
        cfg = load_settings()
        interval_days = int(cfg.get("post_mortem", {}).get("meta_analysis_interval_days", 14))
        state = self._load_pm_state()
        last = state.get("last_meta_analysis_at", 0.0)
        elapsed_days = (time.time() - float(last)) / 86_400
        due = elapsed_days >= interval_days
        if not due:
            logger.debug(
                f"[MetaAnalysis] prochain run dans {interval_days - elapsed_days:.1f} jours"
            )
        return due

    def _run_meta_analysis(self, trigger: str = "auto") -> None:
        """
        Méta-analyse LLM : Claude analyse les patterns d'échec sur les N dernières décisions.

        - Collecte les trades perdants + un échantillon de trades gagnants
        - Construit un prompt structuré
        - Appelle le LLM (même provider que synthesis_agent)
        - Persiste le résultat dans meta_analyses
        - Intervalle configurable : post_mortem.meta_analysis_interval_days (défaut 14)
        """
        if trigger == "auto" and not self._meta_analysis_due():
            return

        try:
            from storage.database import get_decisions_for_meta, save_meta_analysis
            from utils.config import load_settings

            cfg = load_settings()
            days = int(cfg.get("post_mortem", {}).get("meta_analysis_days", 30))

            trades = get_decisions_for_meta(days=days, limit=100)
            if not trades:
                logger.info("[MetaAnalysis] Pas de trades évalués — analyse reportée")
                return

            losing = [t for t in trades if t["result"] < 0]
            winning = [t for t in trades if t["result"] > 0]

            if len(losing) < 5:
                logger.info(
                    f"[MetaAnalysis] Seulement {len(losing)} trades perdants (<5) — reportée"
                )
                return

            logger.info(
                f"[MetaAnalysis] Lancement — {len(losing)} pertes, {len(winning)} gains "
                f"sur {days} jours"
            )

            # Construire le prompt
            def _fmt_trade(t: dict) -> str:
                agents_str = ", ".join(
                    f"{k}={int(v)}" for k, v in (t.get("agents") or {}).items()
                ) or "n/a"
                regime = t.get("regime") or "?"
                return (
                    f"  [{t['ts']}] {t['asset']} {t['action']} score={t['score']:.0f} "
                    f"résultat={t['result']:+.2f}$ | "
                    f"MF={t.get('mf_score') or '?'} MKT={t.get('market_score') or '?'} "
                    f"CTR={t.get('ctr_score') or '?'} régime={regime} | agents: {agents_str}"
                )

            losing_text = "\n".join(_fmt_trade(t) for t in losing[:40])
            winning_sample = winning[:20]
            winning_text = (
                "\n".join(_fmt_trade(t) for t in winning_sample)
                if winning_sample else "  (aucun trade gagnant dans la période)"
            )

            prompt = (
                f"Tu es un analyste quantitatif expert en analyse post-mortem de systèmes de trading algorithmique.\n\n"
                f"Voici {len(losing)} TRADES PERDANTS et {len(winning_sample)} TRADES GAGNANTS "
                f"(pour comparaison) sur les {days} derniers jours.\n\n"
                f"Chaque ligne : [date] actif action score résultat$ | MiroFish MarketData Contrarian régime | scores par agent\n\n"
                f"TRADES PERDANTS (résultat < 0) :\n{losing_text}\n\n"
                f"TRADES GAGNANTS (échantillon) :\n{winning_text}\n\n"
                f"Analyse et réponds en JSON valide avec cette structure exacte :\n"
                f'{{\n'
                f'  "resume": "2-3 phrases de synthèse exécutive",\n'
                f'  "patterns": [\n'
                f'    {{"pattern": "description du pattern", "frequence": "X/Y trades", "impact": "fort|moyen|faible"}}\n'
                f'  ],\n'
                f'  "agents_problematiques": [\n'
                f'    {{"agent": "nom", "probleme": "description", "condition": "dans quel contexte"}}\n'
                f'  ],\n'
                f'  "recos": [\n'
                f'    {{"priorite": 1, "action": "action concrète", "rationale": "pourquoi"}}\n'
                f'  ],\n'
                f'  "points_positifs": "ce qui fonctionne bien dans le système"\n'
                f'}}'
            )

            # Initialiser le LLM
            llm = self._build_llm_for_meta(cfg)
            if llm is None:
                logger.warning("[MetaAnalysis] LLM non disponible — analyse ignorée")
                return

            # Appel LLM avec timeout
            from langchain_core.messages import HumanMessage, SystemMessage
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

            system = (
                "Tu es un expert en trading algorithmique. "
                "Tu analyses les patterns d'échec d'un système de paper-trading multi-actifs. "
                "Réponds UNIQUEMENT en JSON valide, sans markdown, sans commentaires."
            )
            messages = [
                SystemMessage(content=system),
                HumanMessage(content=prompt),
            ]

            timeout_s = int(cfg.get("llm", {}).get("request_timeout_seconds", 60)) + 30
            _pool = ThreadPoolExecutor(max_workers=1)
            _fut = _pool.submit(llm.invoke, messages)
            try:
                response = _fut.result(timeout=timeout_s)
                raw_text = response.content if hasattr(response, "content") else str(response)
            except FuturesTimeout:
                logger.warning("[MetaAnalysis] Timeout LLM — analyse ignorée")
                _pool.shutdown(wait=False)
                return
            finally:
                _pool.shutdown(wait=False)

            # Parser le JSON
            import re as _re
            patterns_json = None
            summary_text = raw_text.strip()
            try:
                # Extraire le JSON de la réponse (peut être entouré de ```json ... ```)
                json_match = _re.search(r'\{[\s\S]*\}', raw_text)
                if json_match:
                    parsed = json.loads(json_match.group())
                    patterns_json = json.dumps(parsed, ensure_ascii=False)
                    # Construire un résumé Markdown depuis le JSON
                    summary_text = self._meta_json_to_markdown(parsed, len(losing), len(winning))
            except Exception as parse_exc:
                logger.debug(f"[MetaAnalysis] JSON parse échoué ({parse_exc}) — texte brut conservé")

            save_meta_analysis(
                summary_text=summary_text,
                n_trades=len(trades),
                n_losing=len(losing),
                patterns_json=patterns_json,
                run_trigger=trigger,
            )
            self._persist_pm_state({"last_meta_analysis_at": time.time()})
            logger.info(
                f"[MetaAnalysis] Analyse sauvegardée — {len(losing)} pertes analysées, "
                f"{len(json.loads(patterns_json).get('recos', [])) if patterns_json else 0} recommandation(s)"
            )

        except Exception as exc:
            logger.warning(f"[MetaAnalysis] Error: {exc}")

    @staticmethod
    def _build_llm_for_meta(cfg: dict):
        """Initialise le LLM selon le provider configuré (même logique que SynthesisAgent)."""
        try:
            from utils.config import get_env
            provider = cfg.get("llm", {}).get("provider", "anthropic")
            model = cfg.get("llm", {}).get("model", "claude-3-5-haiku-20241022")
            temperature = float(cfg.get("llm", {}).get("temperature", 0.2))
            max_tokens = 2048
            timeout_s = int(cfg.get("llm", {}).get("request_timeout_seconds", 60))

            if provider == "anthropic":
                from langchain_anthropic import ChatAnthropic
                return ChatAnthropic(
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    api_key=get_env("ANTHROPIC_API_KEY"),
                    timeout=timeout_s,
                )
            elif provider in ("deepseek", "github", "xai", "openai"):
                from langchain_openai import ChatOpenAI
                base_urls = {
                    "deepseek": "https://api.deepseek.com/v1",
                    "github": "https://models.inference.ai.azure.com",
                    "xai": "https://api.x.ai/v1",
                    "openai": None,
                }
                api_keys = {
                    "deepseek": get_env("DEEPSEEK_API_KEY"),
                    "github": get_env("GITHUB_TOKEN"),
                    "xai": get_env("XAI_API_KEY"),
                    "openai": get_env("OPENAI_API_KEY"),
                }
                kwargs = dict(model=model, temperature=temperature, max_tokens=max_tokens,
                              openai_api_key=api_keys[provider], request_timeout=timeout_s)
                if base_urls[provider]:
                    kwargs["openai_api_base"] = base_urls[provider]
                return ChatOpenAI(**kwargs)
            elif provider == "ollama":
                from langchain_openai import ChatOpenAI
                base_url = get_env("OLLAMA_BASE_URL", required=False, default="http://localhost:11434/v1")
                return ChatOpenAI(model=model, temperature=temperature, max_tokens=max_tokens,
                                  openai_api_key="ollama", openai_api_base=base_url,
                                  request_timeout=timeout_s)
        except Exception as exc:
            logger.warning(f"[MetaAnalysis] LLM init échoué : {exc}")
        return None

    def run_meta_analysis_now(self) -> None:
        """Méthode publique pour forcer une méta-analyse depuis le dashboard Admin."""
        self._run_meta_analysis(trigger="manual")

    @staticmethod
    def _meta_json_to_markdown(data: dict, n_losing: int, n_winning: int) -> str:
        """Convertit le JSON structuré de méta-analyse en Markdown lisible."""
        lines = []
        lines.append(f"## 📋 Résumé")
        lines.append(data.get("resume", "_Non disponible_"))
        lines.append(f"\n_Basé sur **{n_losing}** trades perdants et **{n_winning}** trades gagnants._")

        patterns = data.get("patterns", [])
        if patterns:
            lines.append("\n## 🔴 Patterns d'échec récurrents")
            for p in patterns:
                impact = p.get("impact", "?")
                icon = "🔴" if impact == "fort" else ("🟡" if impact == "moyen" else "🟢")
                lines.append(
                    f"- {icon} **{p.get('pattern', '?')}** "
                    f"_(fréquence: {p.get('frequence', '?')})_"
                )

        agents = data.get("agents_problematiques", [])
        if agents:
            lines.append("\n## ⚠️ Agents problématiques")
            for a in agents:
                lines.append(
                    f"- **{a.get('agent', '?')}** : {a.get('probleme', '?')}"
                    f"\n  ↳ _Condition : {a.get('condition', '?')}_"
                )

        recos = data.get("recos", [])
        if recos:
            lines.append("\n## ✅ Recommandations")
            for r in sorted(recos, key=lambda x: x.get("priorite", 99)):
                lines.append(
                    f"{r.get('priorite', '?')}. **{r.get('action', '?')}**"
                    f"\n   → {r.get('rationale', '')}"
                )

        positifs = data.get("points_positifs", "")
        if positifs:
            lines.append(f"\n## 💚 Points positifs\n{positifs}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # F7 — Champion-Challenger
    # ------------------------------------------------------------------
    def _maybe_promote_champion(self) -> None:
        """
        F7 — Si un profil shadow surperforme le baseline sur >=20 cycles
        (+15% win rate ET +20% P&L), envoie une notification.
        """
        try:
            from storage.database import get_shadow_comparison_stats, get_pnl_history

            stats = get_shadow_comparison_stats()
            if not stats:
                return

            # Baseline : win_rate et P&L du profil live
            live_history = [
                h for h in get_pnl_history() if h.get("result_24h") is not None
            ][-50:]
            if not live_history:
                return

            live_wins = sum(1 for h in live_history if (h.get("result_24h") or 0) > 0)
            baseline_win_rate = live_wins / max(len(live_history), 1)
            baseline_pnl = sum(h.get("result_24h", 0) or 0 for h in live_history)

            for s in stats:
                total = s.get("total_trades", 0)
                if total < 20:
                    continue
                shadow_wr = s.get("win_rate", 0)
                shadow_pnl = s.get("total_pnl", 0)

                wr_threshold = baseline_win_rate * 1.15  # +15%
                pnl_threshold = baseline_pnl * 1.20 if baseline_pnl > 0 else 1.0

                if shadow_wr > wr_threshold and shadow_pnl > pnl_threshold:
                    logger.warning(
                        f"CHAMPION detecte : profil '{s['profile']}' — "
                        f"win_rate={shadow_wr:.0%} (base={baseline_win_rate:.0%}) "
                        f"pnl={shadow_pnl:.2f}$ (base={baseline_pnl:.2f}$)"
                    )
                    self._notify_champion(s)
        except Exception as exc:
            logger.debug(f"Champion-challenger check echoue: {exc}")

    @staticmethod
    def _notify_champion(shadow_stats: dict) -> None:
        """Envoie une notification champion via le systeme d'alertes."""
        try:
            from utils.notifier import get_notifier
            notifier = get_notifier()
            if notifier:
                profile = shadow_stats.get("profile", "?")
                wr = shadow_stats.get("win_rate", 0)
                pnl = shadow_stats.get("total_pnl", 0)
                notifier.notify(
                    f"Champion detecte : profil '{profile}' surperforme le baseline\n"
                    f"Win rate: {wr:.0%} | P&L: ${pnl:.2f}"
                )
        except Exception:
            pass


def get_calibrated_probability(score: float) -> float | None:
    """
    Retourne la probabilite calibree (isotonique) associee a un score [0-100].
    Retourne None si la calibration n'est pas encore disponible.
    """
    try:
        if not _CALIBRATION_PATH.exists():
            return None
        with open(_CALIBRATION_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        mapping = data.get("map", {})
        key = str(int(round(score)))
        if key in mapping:
            return float(mapping[key])
    except Exception:
        pass
    return None
