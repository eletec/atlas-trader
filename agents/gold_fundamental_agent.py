"""
agents/gold_fundamental_agent.py — Fondamentaux spécifiques à XAU/USD (Or).

Sources (sans clé API sauf FRED_API_KEY optionnel) :
  - GoldAPI.io / metals-api : prix spot or (fallback Yahoo Finance)
  - FRED (Federal Reserve)  : M2 supply, CPI, TIPS yields (clé gratuite)
  - World Gold Council RSS  : publications officielles
  - BullionVault / Kitco RSS: flux or

L'or est piloté par : taux réels (TIPS), DXY, M2, inflation, géopolitique.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request

logger = logging.getLogger("zeitgeist.gold_fundamental")

_TIMEOUT = 10


def _get(url: str, headers: dict | None = None) -> dict | list | None:
    h = {"User-Agent": "atlas-trader/2.0", **(headers or {})}
    try:
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        logger.debug(f"Gold onchain GET {url[:60]}… → {exc}")
        return None


class GoldFundamentalAgent:
    """
    Analyse fondamentale macro pour XAU/USD.
    Interface identique à FundamentalAgent.analyze()
    """

    def __init__(self):
        from utils.config import load_settings
        cfg = load_settings()
        self._llm_cfg = cfg.get("llm", {})

    # ------------------------------------------------------------------ #
    #  Interface publique                                                  #
    # ------------------------------------------------------------------ #

    def analyze(self, state: dict) -> dict:
        indicators = state.get("market_indicators", {}) or {}
        rule_result = self._rule_based(indicators)

        air = state.get("air_du_temps") or {}
        try:
            macro = self._fetch_macro_metrics()
            llm_result = self._analyze_with_llm(indicators, air, macro)
            blended = round(llm_result["score"] * 0.6 + rule_result["score"] * 0.4, 1)
            return {
                "agent_name": "gold_fundamental",
                "score": blended,
                "signal": (
                    "BULLISH" if blended > 60
                    else ("BEARISH" if blended < 40 else "NEUTRAL")
                ),
                "summary": llm_result["summary"],
                "confidence": round(
                    llm_result["confidence"] * 0.6 + rule_result["confidence"] * 0.4, 2
                ),
                "rule_score": rule_result["score"],
                "llm_score": llm_result["score"],
                "macro": macro,
            }
        except Exception as exc:
            logger.warning(f"GoldFundamentalAgent LLM fallback (rules): {exc}")
            return rule_result

    # ------------------------------------------------------------------ #
    #  Macro data collection                                               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _fetch_macro_metrics() -> dict:
        """
        Collecte les indicateurs macro pertinents pour l'or.
        Retourne un dict — aucune exception levée.
        """
        data: dict = {}

        # 1. Prix spot or via GoldAPI (sans clé)
        r = _get("https://data-asg.goldprice.org/dbXRates/USD")
        if r and isinstance(r, dict):
            items = r.get("items", [])
            for item in items:
                if item.get("curr") == "XAU":
                    data["gold_spot"] = float(item.get("xauPrice", 0))
                    break

        # 2. DXY (Dollar Index) via Yahoo Finance (pas de clé)
        try:
            r = _get(
                "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB"
                "?interval=1d&range=5d",
                headers={"Accept": "application/json"},
            )
            if r:
                result = r.get("chart", {}).get("result", [{}])
                if result:
                    closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
                    closes = [c for c in closes if c]
                    if closes:
                        data["dxy"] = float(closes[-1])
        except Exception:
            pass

        # 3. TIPS 10 ans (taux réels) — variable Fed cruciale pour l'or
        # FRED (clé gratuite sur fred.stlouisfed.org)
        fred_key = os.environ.get("FRED_API_KEY", "")
        if fred_key:
            # DFII10 = 10-Year Treasury Inflation-Indexed Security, Constant Maturity
            r = _get(
                f"https://api.stlouisfed.org/fred/series/observations"
                f"?series_id=DFII10&api_key={fred_key}&file_type=json"
                f"&sort_order=desc&limit=1"
            )
            if r and r.get("observations"):
                val = r["observations"][0].get("value", ".")
                if val != ".":
                    data["tips_10y"] = float(val)

            # M2 Money Supply (M2SL) — expansion monétaire corrélée à l'or
            r = _get(
                f"https://api.stlouisfed.org/fred/series/observations"
                f"?series_id=M2SL&api_key={fred_key}&file_type=json"
                f"&sort_order=desc&limit=2"
            )
            if r and r.get("observations"):
                obs = r["observations"]
                if len(obs) >= 2:
                    try:
                        v_new = float(obs[0]["value"])
                        v_old = float(obs[1]["value"])
                        data["m2_growth_pct"] = (v_new - v_old) / v_old * 100
                    except (ValueError, ZeroDivisionError):
                        pass

        # 4. CPI YoY (CoinGecko ne couvre pas les données macro → approximation d'après
        # le Kitco RSS ou le Yahoo Finance pour CPIAUCSL)
        try:
            r = _get(
                "https://query1.finance.yahoo.com/v8/finance/chart/%5ETNX"
                "?interval=1d&range=5d",
                headers={"Accept": "application/json"},
            )
            if r:
                result = r.get("chart", {}).get("result", [{}])
                if result:
                    closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
                    closes = [c for c in closes if c]
                    if closes:
                        data["tnx_10y_yield"] = float(closes[-1])  # taux nominaux 10 ans US
        except Exception:
            pass

        # 5. GLD ETF flows (approximation via volume Yahoo Finance)
        try:
            r = _get(
                "https://query1.finance.yahoo.com/v8/finance/chart/GLD"
                "?interval=1d&range=5d",
                headers={"Accept": "application/json"},
            )
            if r:
                result = r.get("chart", {}).get("result", [{}])
                if result:
                    vols = result[0].get("indicators", {}).get("quote", [{}])[0].get("volume", [])
                    vols = [v for v in vols if v]
                    if len(vols) >= 2:
                        data["gld_vol_change_pct"] = (vols[-1] - vols[-2]) / vols[-2] * 100

        except Exception:
            pass

        return data

    # ------------------------------------------------------------------ #
    #  LLM analysis                                                        #
    # ------------------------------------------------------------------ #

    def _analyze_with_llm(self, indicators: dict, air: dict, macro: dict) -> dict:
        price = indicators.get("price", 0)
        ma_50 = indicators.get("ma_50", 0)
        rsi = indicators.get("rsi_14", 50)
        rsi_1h = indicators.get("rsi_1h", "N/A")
        macd = indicators.get("macd", 0)
        macd_sig = indicators.get("macd_signal", 0)

        macro_lines = []
        if "dxy" in macro:
            macro_lines.append(f"- DXY (Dollar Index): {macro['dxy']:.2f}")
        if "tips_10y" in macro:
            macro_lines.append(f"- TIPS 10y (real rate): {macro['tips_10y']:.2f}%")
        if "tnx_10y_yield" in macro:
            macro_lines.append(f"- UST 10y nominal yield: {macro['tnx_10y_yield']:.2f}%")
        if "m2_growth_pct" in macro:
            macro_lines.append(f"- M2 growth MoM: {macro['m2_growth_pct']:+.2f}%")
        if "gold_spot" in macro:
            macro_lines.append(f"- Gold spot (GoldAPI): ${macro['gold_spot']:.2f}")
        if "gld_vol_change_pct" in macro:
            macro_lines.append(f"- GLD ETF volume change: {macro['gld_vol_change_pct']:+.1f}%")

        air_summary = (air.get("summary", "N/A") or "N/A")[:300]

        prompt = (
            "You are a senior precious metals analyst. Analyze XAU/USD prospects and give "
            "a conviction score [0-100] for going LONG.\n\n"
            f"XAU/USD Technical Data:\n"
            f"- Price: ${price:,.2f} | MA50: ${ma_50:,.2f} "
            f"({'ABOVE' if price > ma_50 else 'BELOW'} MA50)\n"
            f"- RSI-14: {rsi:.1f} | RSI-1h: {rsi_1h}\n"
            f"- MACD: {macd:.4f} vs signal {macd_sig:.4f} "
            f"({'bullish' if macd > macd_sig else 'bearish'})\n\n"
            f"Macro indicators:\n" + ("\n".join(macro_lines) or "N/A") + "\n\n"
            f"Context:\n{air_summary}\n\n"
            "Reminder: Gold rises when real rates fall, DXY weakens, M2 expands, "
            "geopolitical risk increases, or inflation expectations rise.\n\n"
            "Respond in strict JSON:\n"
            '{"score": <0-100>, "signal": "BULLISH"|"NEUTRAL"|"BEARISH", '
            '"summary": "<2-3 sentences max>", "confidence": <0.0-1.0>}'
        )

        provider = self._llm_cfg.get("provider", "anthropic")
        if provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(timeout=60.0)
            resp = client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
        else:
            from openai import OpenAI
            base_url = None
            api_key_env = "OPENAI_API_KEY"
            model = self._llm_cfg.get("model", "gpt-4o-mini")
            if provider == "deepseek":
                base_url = "https://api.deepseek.com/v1"
                api_key_env = "DEEPSEEK_API_KEY"
                model = "deepseek-chat"
            client = OpenAI(api_key=os.environ.get(api_key_env, ""), base_url=base_url, timeout=60)
            resp = client.chat.completions.create(
                model=model, max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.choices[0].message.content.strip()

        json_start = raw.find("{")
        json_end = raw.rfind("}") + 1
        d = json.loads(raw[json_start:json_end])
        score = float(d.get("score", 50))
        signal = str(d.get("signal", "NEUTRAL")).upper()
        if signal not in ("BULLISH", "BEARISH", "NEUTRAL"):
            signal = "BULLISH" if score > 60 else ("BEARISH" if score < 40 else "NEUTRAL")
        return {
            "score": round(score, 1),
            "signal": signal,
            "summary": str(d.get("summary", "Analyse macro or LLM")),
            "confidence": float(d.get("confidence", 0.7)),
        }

    # ------------------------------------------------------------------ #
    #  Rule-based fallback                                                 #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _rule_based(indicators: dict) -> dict:
        score = 50.0

        rsi = indicators.get("rsi_14", 50)
        if rsi <= 30:
            score += 15
        elif rsi <= 40:
            score += 8
        elif rsi >= 70:
            score -= 15
        elif rsi >= 60:
            score -= 5

        macd = indicators.get("macd", 0)
        macd_sig = indicators.get("macd_signal", 0)
        if macd and macd_sig:
            score += 8 if macd > macd_sig else -8

        price = indicators.get("price", 0)
        ma_50 = indicators.get("ma_50", 0)
        if price and ma_50:
            score += 5 if price > ma_50 else -7

        score = max(0.0, min(100.0, score))
        return {
            "agent_name": "gold_fundamental",
            "score": round(score, 1),
            "signal": (
                "BULLISH" if score > 60 else ("BEARISH" if score < 40 else "NEUTRAL")
            ),
            "summary": "Analyse XAU rule-based (LLM indisponible)",
            "confidence": 0.50,
        }
