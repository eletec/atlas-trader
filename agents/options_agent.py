"""
agents/options_agent.py — Signal volatilite implicite et put/call ratio.
Utilise l'API publique Deribit (sans cle API requise).

Signaux :
  IV > 80% → forte volatilite attendue (risque bi-directionnel)
  Put/Call ratio > 1.5 → sentiment bearish
  Put/Call ratio < 0.7 → exuberance (signal contrarien bearish)
"""
from __future__ import annotations

import logging

logger = logging.getLogger("zeitgeist.options")

_DERIBIT_URL = "https://www.deribit.com/api/v2/public"


class OptionsAgent:
    """Signal derive : volatilite implicite et put/call ratio BTC (Deribit)."""

    def analyze(self, state: dict) -> dict:
        """Retourne un score base sur la volatilite implicite et le put/call ratio."""
        iv = self._get_atm_iv()
        pcr = self._get_put_call_ratio()

        score = 50.0
        signals = []

        # --- IV : haute volatilite = risque => penaliser les positions directionnelles ---
        if iv is not None:
            if iv > 80:
                score -= 10
                signals.append(f"IV elevee ({iv:.0f}%) — volatilite extreme attendue")
            elif iv > 60:
                score -= 5
                signals.append(f"IV moderee-haute ({iv:.0f}%)")
            elif iv < 30:
                score += 5
                signals.append(f"IV basse ({iv:.0f}%) — marche calme")
            else:
                signals.append(f"IV normale ({iv:.0f}%)")

        # --- Put/Call Ratio : position des hedgers ---
        if pcr is not None:
            if pcr > 1.5:
                score -= 12
                signals.append(f"Put/Call eleve ({pcr:.2f}) — protection baissiere dominante")
            elif pcr > 1.2:
                score -= 6
                signals.append(f"Put/Call haut ({pcr:.2f}) — prudence")
            elif pcr < 0.7:
                # Trop d'optimisme = signal contrarien bearish
                score -= 8
                signals.append(f"Put/Call bas ({pcr:.2f}) — exuberance (signal contrarien)")
            elif pcr < 0.9:
                score += 5
                signals.append(f"Put/Call equilibre bas ({pcr:.2f}) — sentiment positif")
            else:
                signals.append(f"Put/Call neutre ({pcr:.2f})")

        score = max(0, min(100, score))
        signal = "BULLISH" if score > 60 else ("BEARISH" if score < 40 else "NEUTRAL")
        confidence = 0.6 if (iv is not None and pcr is not None) else (0.35 if iv or pcr else 0.1)

        logger.debug(f"Options score={score:.0f} IV={iv} PCR={pcr}")
        return {
            "agent_name": "options",
            "score": round(score, 1),
            "signal": signal,
            "summary": " | ".join(signals) if signals else "Donnees options indisponibles",
            "confidence": round(confidence, 2),
            "iv_percent": iv,
            "put_call_ratio": pcr,
        }

    @staticmethod
    def _get_atm_iv() -> float | None:
        """
        Recupere la volatilite implicite ATM BTC ~7 jours via Deribit.
        Utilise l'index de volatilite DVol BTC directement (le plus fiable).
        """
        try:
            from utils.http_session import get_http_session
            resp = get_http_session().get(
                f"{_DERIBIT_URL}/get_volatility_index_data",
                params={"currency": "BTC", "resolution": "3600", "count": 1},
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json().get("result", {})
            ticks = data.get("data", [])
            if ticks:
                # Format: [timestamp, open, high, low, close]
                return round(float(ticks[-1][4]), 1)
        except Exception as exc:
            logger.debug(f"Deribit DVol IV indisponible: {exc}")
        return None

    @staticmethod
    def _get_put_call_ratio() -> float | None:
        """
        Calcule le put/call ratio volume 24h sur les options BTC Deribit.
        Agregation des volumes put vs call dans le book summary.
        """
        try:
            from utils.http_session import get_http_session
            resp = get_http_session().get(
                f"{_DERIBIT_URL}/get_book_summary_by_currency",
                params={"currency": "BTC", "kind": "option"},
                timeout=10,
            )
            resp.raise_for_status()
            instruments = resp.json().get("result", [])
            put_vol = 0.0
            call_vol = 0.0
            for inst in instruments:
                name = inst.get("instrument_name", "")
                vol = float(inst.get("volume", 0) or 0)
                if name.endswith("-P"):
                    put_vol += vol
                elif name.endswith("-C"):
                    call_vol += vol
            if call_vol > 0:
                return round(put_vol / call_vol, 3)
        except Exception as exc:
            logger.debug(f"Deribit put/call ratio indisponible: {exc}")
        return None
