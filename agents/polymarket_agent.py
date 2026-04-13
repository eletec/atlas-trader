"""
agents/polymarket_agent.py — Polymarket Prediction Market Agent.

Interroge les marchés prédictifs Polymarket sur BTC pour extraire
un signal de probabilité calibré. Les marchés Polymarket calibrés
(gap maker-taker ~2.69 pp sur crypto) donnent des probabilités
fiables utilisables comme signal directionnel.

API gratuite, sans clé. Endpoint REST :
  GET https://gamma-api.polymarket.com/markets?tag_slug=bitcoin&active=true&closed=false

Logique :
  1. Récupère les marchés BTC actifs
  2. Classifie chaque marché : question haussière ou baissière
  3. Calcule la probabilité haussière agrégée (pondérée par volume)
  4. Signal contrarien longshot : si gros volume sur YES très improbable → les takers
     se trompent historiquement → signal légèrement baissier

Score 0-100 → BULLISH si > 58, BEARISH si < 42, sinon NEUTRAL.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from functools import lru_cache


@lru_cache(maxsize=1)
def _find_polyterm_bin() -> str:
    """P1: cache le chemin du binaire polyterm — ne change pas en cours d'exécution."""
    return (
        shutil.which("polyterm")
        or shutil.which("polyterm", path="/app/.local/bin:/usr/local/bin:/usr/bin")
        or "/app/.local/bin/polyterm"
    )

logger = logging.getLogger("zeitgeist.polymarket")

# Mots-clés pour classifier la direction d'une question
_BULLISH_KEYWORDS = re.compile(
    r"\b(above|over|exceed|reach|hit|surpass|rise|rally|bull|break|higher|top|up)\b",
    re.IGNORECASE,
)
_BEARISH_KEYWORDS = re.compile(
    r"\b(below|under|fall|drop|decline|crash|dump|bear|lower|lose|dip|down)\b",
    re.IGNORECASE,
)

# Seuil de probabilité "longshot" : YES < 15% mais gros volume → les takers se trompent
_LONGSHOT_THRESHOLD = 0.15
_LONGSHOT_VOLUME_MIN = 20_000   # $USD de volume minimal pour considérer le signal


class PolymarketAgent:
    """Agent Polymarket — probabilités calibrées sur marchés prédictifs BTC."""

    _API_URL = (
        "https://gamma-api.polymarket.com/markets"
        "?tag_slug=bitcoin&active=true&closed=false&limit=30"
    )

    def analyze(self, state: dict) -> dict:
        try:
            from utils.http_session import get_http_session

            resp = get_http_session().get(
                self._API_URL,
                timeout=10,
            )
            resp.raise_for_status()
            markets = resp.json()

            if not markets:
                return self._fallback("aucun marché BTC actif")

            bullish_probs: list[float] = []
            volumes: list[float] = []
            longshot_volume = 0.0
            parsed_markets: list[dict] = []

            for mkt in markets:
                question = mkt.get("question", "")
                prices_raw = mkt.get("outcomePrices", "[]")
                outcomes_raw = mkt.get("outcomes", "[]")
                volume = float(mkt.get("volume", 0) or 0)

                # outcomePrices est une chaîne JSON : '["0.62", "0.38"]'
                try:
                    prices = [float(p) for p in json.loads(prices_raw)]
                    outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue

                if not prices:
                    continue

                # Trouver l'index YES
                yes_idx = 0
                if isinstance(outcomes, list):
                    for i, o in enumerate(outcomes):
                        if str(o).strip().upper() in ("YES", "OUI"):
                            yes_idx = i
                            break

                yes_price = prices[yes_idx] if yes_idx < len(prices) else prices[0]

                # Classifier la question
                is_bullish_q = bool(_BULLISH_KEYWORDS.search(question))
                is_bearish_q = bool(_BEARISH_KEYWORDS.search(question))

                if is_bullish_q and not is_bearish_q:
                    # "Will BTC reach $X?" → YES_price = probabilité haussière
                    bullish_prob = yes_price
                    direction = "bullish"
                elif is_bearish_q and not is_bullish_q:
                    # "Will BTC fall below $X?" → prob haussière = 1 - YES_price
                    bullish_prob = 1.0 - yes_price
                    direction = "bearish"
                else:
                    # Question ambiguë → ignore
                    continue

                bullish_probs.append(bullish_prob)
                volumes.append(volume)
                parsed_markets.append({
                    "q": question[:60],
                    "direction": direction,
                    "prob": round(bullish_prob, 3),
                    "vol": volume,
                })

                # Signal longshot contrarien : gros volume sur YES très improbable
                # (les takers parient sur un évènement improbable → historiquement faux)
                if direction == "bullish" and yes_price < _LONGSHOT_THRESHOLD:
                    longshot_volume += volume
                elif direction == "bearish" and (1 - yes_price) < _LONGSHOT_THRESHOLD:
                    longshot_volume += volume

            if not bullish_probs:
                return self._fallback("aucune question classifiable")

            # Probabilité haussière agrégée (pondérée par volume, ou simple si volume=0)
            total_vol = sum(volumes)
            if total_vol > 0:
                avg_bullish = sum(p * v for p, v in zip(bullish_probs, volumes)) / total_vol
            else:
                avg_bullish = sum(bullish_probs) / len(bullish_probs)

            # Score de base
            trader_score = avg_bullish * 100.0

            # Ajustement longshot contrarien (max -10 pts)
            longshot_penalty = 0.0
            if longshot_volume >= _LONGSHOT_VOLUME_MIN:
                # Pénalité logarithmique, plafonnée à 10 pts
                import math
                longshot_penalty = min(10.0, math.log10(longshot_volume / _LONGSHOT_VOLUME_MIN) * 4)
                trader_score -= longshot_penalty

            # Enrichissement polyterm : signal whale / smart-money (max ±15 pts)
            whale_adjustment, whale_summary = self._get_polyterm_signal()
            trader_score += whale_adjustment

            # Borner le score
            trader_score = max(10.0, min(90.0, trader_score))

            # Signal
            if trader_score > 58:
                signal = "BULLISH"
            elif trader_score < 42:
                signal = "BEARISH"
            else:
                signal = "NEUTRAL"

            # Résumé
            n = len(parsed_markets)
            top = sorted(parsed_markets, key=lambda x: x["vol"], reverse=True)[:3]
            top_strs = [f"« {m['q']} » → {m['prob']*100:.0f}%" for m in top]
            summary = (
                f"Polymarket BTC ({n} marchés analysés) — "
                f"Probabilité haussière agrégée : {avg_bullish*100:.1f}%. "
                f"Marchés clés : {' | '.join(top_strs)}."
            )
            if longshot_penalty > 0:
                summary += (
                    f" ⚠️ Signal contrarien : ${longshot_volume:,.0f} de volume "
                    f"sur paris longshots (−{longshot_penalty:.1f} pts)."
                )
            if whale_summary:
                summary += f" {whale_summary}"

            logger.info(
                f"Polymarket: avg_bullish={avg_bullish*100:.1f}% "
                f"n={n} longshot_vol={longshot_volume:.0f} "
                f"whale_adj={whale_adjustment:+.1f} "
                f"→ score={trader_score:.1f} [{signal}]"
            )

            return {
                "agent_name": "polymarket",
                "score": round(trader_score, 1),
                "signal": signal,
                "summary": summary,
                "confidence": 0.80,
                "avg_bullish_prob": round(avg_bullish, 4),
                "n_markets": n,
                "longshot_volume_usd": round(longshot_volume, 0),
            }

        except Exception as exc:
            logger.warning(f"PolymarketAgent error: {exc}")
            return self._fallback(str(exc))

    @staticmethod
    def _get_polyterm_signal() -> tuple[float, str]:
        """
        Appelle `polyterm predict --format json --limit 30` en subprocess pour enrichir
        le signal avec les prédictions multi-facteurs de polyterm (momentum, volume,
        whale activity, smart money quand disponible).

        Retourne (adjustment: float [-15, +15], summary: str).
        Retourne (0.0, "") si polyterm est indisponible ou renvoie des données inutilisables.

        NE PAS utiliser `with ThreadPoolExecutor` ici — voir synthesis_agent.py.
        """
        try:
            _polyterm_bin = _find_polyterm_bin()
            result = subprocess.run(
                [_polyterm_bin, "predict", "--format", "json", "--limit", "30"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return 0.0, ""

            data = json.loads(result.stdout)
            if data.get("success") is False:
                return 0.0, ""

            predictions = data.get("predictions", [])
            if not predictions:
                return 0.0, ""

            # Agréger direction pondérée par confidence — toutes les prédictions
            # (les marchés BTC ne sont pas toujours dans le top par volume ;
            #  le sentiment global Polymarket reste un proxy risque valide)
            # Seuil de confiance minimal pour éviter le bruit des prédictions incertaines
            _MIN_CONF = 0.5
            bullish_w = 0.0
            bearish_w = 0.0
            for p in predictions:
                conf = float(p.get("confidence", 0.0))
                if conf < _MIN_CONF:
                    continue  # ignorer les prédictions peu confiantes
                direction = str(p.get("direction", "neutral")).lower()
                if direction == "bullish":
                    bullish_w += conf
                elif direction == "bearish":
                    bearish_w += conf

            total_w = bullish_w + bearish_w
            if total_w == 0:
                return 0.0, ""

            # Ratio haussier [0..1] → ajustement plafonné à ±8 pts
            # (signal indirect — marchés non-BTC → poids modéré)
            bullish_ratio = bullish_w / total_w
            adjustment = (bullish_ratio - 0.5) * 16.0  # max ±8 pts

            n = len(predictions)
            n_active = int(bullish_w + bearish_w > 0 and sum(
                1 for p in predictions if float(p.get("confidence", 0)) >= _MIN_CONF
                and str(p.get("direction", "neutral")).lower() in ("bullish", "bearish")
            ))
            bull_pct = bullish_ratio * 100
            avg_conf = total_w / max(1, n_active)
            summary = (
                f"Polyterm sentiment global ({n_active} marchés conf≥50%, conf. moy. {avg_conf:.0%}) : "
                f"{bull_pct:.0f}% haussier → {adjustment:+.1f} pts."
            )
            logger.info(
                f"Polyterm signal: n_total={n} n_active={n_active} bull_ratio={bullish_ratio:.2f} "
                f"adj={adjustment:+.1f} avg_conf={avg_conf:.2f}"
            )
            return adjustment, summary

        except (subprocess.TimeoutExpired, FileNotFoundError):
            # polyterm absent ou trop lent — silencieux, pas une erreur critique
            return 0.0, ""
        except Exception as exc:
            logger.debug(f"Polyterm signal ignoré: {exc}")
            return 0.0, ""

    @staticmethod
    def _fallback(reason: str) -> dict:
        logger.warning(f"PolymarketAgent fallback: {reason}")
        return {
            "agent_name": "polymarket",
            "score": 50.0,
            "signal": "NEUTRAL",
            "summary": f"Polymarket indisponible : {reason}",
            "confidence": 0.0,
            "avg_bullish_prob": None,
            "n_markets": 0,
            "longshot_volume_usd": 0,
        }
