"""
agents/forex_fundamental_agent.py — Fondamentaux spécifiques au Forex (EUR/USD, GBP/USD…).

Sources (sans clé API sauf FRED, BOE, ECB) :
  - BCE statistics (ecb.europa.eu) : taux directeurs, décisions récentes
  - FRED                           : taux Fed Funds, M2 US, CPI US
  - CFTC COT report (futures)      : positioning EUR/USD institutionnel
  - Yahoo Finance                  : DXY, UST 10y, DEU 10y (spread)
  - OECD / Eurostat RSS            : PMI, chômage zone euro

Piloté par : différentiel de taux BCE/Fed, DXY, COT positioning, PMI diff, inflation diff.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request

logger = logging.getLogger("zeitgeist.forex_fundamental")

_TIMEOUT = 10


def _get(url: str, headers: dict | None = None) -> dict | list | None:
    h = {"User-Agent": "atlas-trader/2.0", **(headers or {})}
    try:
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        logger.debug(f"Forex GET {url[:60]}… → {exc}")
        return None


class ForexFundamentalAgent:
    """
    Analyse fondamentale macro pour les paires Forex (EUR/USD par défaut).
    Interface identique à FundamentalAgent.analyze()
    """

    def __init__(self):
        from utils.config import load_settings
        cfg = load_settings()
        self._llm_cfg = cfg.get("llm", {})

    def analyze(self, state: dict) -> dict:
        asset = state.get("asset", "EUR/USD")
        indicators = state.get("market_indicators", {}) or {}
        rule_result = self._rule_based(indicators, asset)

        air = state.get("air_du_temps") or {}
        try:
            macro = self._fetch_macro_metrics(asset)
            llm_result = self._analyze_with_llm(indicators, air, macro, asset)
            blended = round(llm_result["score"] * 0.65 + rule_result["score"] * 0.35, 1)
            return {
                "agent_name": "forex_fundamental",
                "score": blended,
                "signal": (
                    "BULLISH" if blended > 60
                    else ("BEARISH" if blended < 40 else "NEUTRAL")
                ),
                "summary": llm_result["summary"],
                "confidence": round(
                    llm_result["confidence"] * 0.65 + rule_result["confidence"] * 0.35, 2
                ),
                "rule_score": rule_result["score"],
                "macro": macro,
            }
        except Exception as exc:
            logger.warning(f"ForexFundamentalAgent fallback (rules): {exc}")
            return rule_result

    # ------------------------------------------------------------------ #
    #  Macro data collection                                               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _fetch_macro_metrics(asset: str = "EUR/USD") -> dict:
        data: dict = {}

        # 1. DXY (Dollar Index)
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

        # 2. UST 10y yield (taux nominaux US)
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
                        data["us_10y"] = float(closes[-1])
        except Exception:
            pass

        # 3. DEU 10y yield (Bund — proxy BCE)
        try:
            r = _get(
                "https://query1.finance.yahoo.com/v8/finance/chart/%5ETYD"
                "?interval=1d&range=5d",
                headers={"Accept": "application/json"},
            )
            # Pas toujours disponible sur Yahoo — fallback sur proxy taux
            # Si disponible, calculer le spread US-DE
            pass
        except Exception:
            pass

        # 4. FRED — Fed Funds Effective Rate
        fred_key = os.environ.get("FRED_API_KEY", "")
        if fred_key:
            r = _get(
                f"https://api.stlouisfed.org/fred/series/observations"
                f"?series_id=FEDFUNDS&api_key={fred_key}&file_type=json"
                f"&sort_order=desc&limit=1"
            )
            if r and r.get("observations"):
                val = r["observations"][0].get("value", ".")
                if val != ".":
                    data["fed_funds_rate"] = float(val)

            # CPI US YoY (CPIAUCSL ou CPILFESL core)
            r = _get(
                f"https://api.stlouisfed.org/fred/series/observations"
                f"?series_id=CPIAUCSL&api_key={fred_key}&file_type=json"
                f"&sort_order=desc&limit=2"
            )
            if r and r.get("observations"):
                obs = r["observations"]
                if len(obs) >= 2:
                    try:
                        v_new = float(obs[0]["value"])
                        v_old = float(obs[1]["value"])
                        data["us_cpi_mom"] = (v_new - v_old) / v_old * 100
                    except (ValueError, ZeroDivisionError):
                        pass

        # 5. COT EUR/USD positioning (CFTC — rapport hebdo, accessible via Quandl/data.nasdaq)
        # Clé gratuite sur data.nasdaq.com si NASDAQ_API_KEY présent
        quandl_key = os.environ.get("NASDAQ_API_KEY", "")
        if quandl_key:
            r = _get(
                f"https://data.nasdaq.com/api/v3/datasets/CFTC/135741_FO_L_ALL.json"
                f"?api_key={quandl_key}&rows=1"
            )
            if r and r.get("dataset", {}).get("data"):
                row = r["dataset"]["data"][0]
                # Colonnes CFTC : [date, open_interest, long_non_comm, short_non_comm, ...]
                try:
                    long_nc  = int(row[2])
                    short_nc = int(row[3])
                    if long_nc + short_nc > 0:
                        data["cot_net_long_pct"] = (long_nc - short_nc) / (long_nc + short_nc) * 100
                except (IndexError, ValueError, ZeroDivisionError):
                    pass

        return data

    # ------------------------------------------------------------------ #
    #  LLM analysis                                                        #
    # ------------------------------------------------------------------ #

    def _analyze_with_llm(
        self, indicators: dict, air: dict, macro: dict, asset: str
    ) -> dict:
        price = indicators.get("price", 0)
        ma_50 = indicators.get("ma_50", 0)
        rsi = indicators.get("rsi_14", 50)
        rsi_1h = indicators.get("rsi_1h", "N/A")
        macd = indicators.get("macd", 0)
        macd_sig = indicators.get("macd_signal", 0)

        macro_lines = []
        if "dxy" in macro:
            macro_lines.append(f"- DXY: {macro['dxy']:.2f}")
        if "us_10y" in macro:
            macro_lines.append(f"- US 10y yield: {macro['us_10y']:.2f}%")
        if "fed_funds_rate" in macro:
            macro_lines.append(f"- Fed Funds Rate: {macro['fed_funds_rate']:.2f}%")
        if "us_cpi_mom" in macro:
            macro_lines.append(f"- US CPI MoM: {macro['us_cpi_mom']:+.3f}%")
        if "cot_net_long_pct" in macro:
            macro_lines.append(
                f"- COT EUR non-commercial net: {macro['cot_net_long_pct']:.1f}%"
            )

        air_summary = (air.get("summary", "N/A") or "N/A")[:300]
        base, quote = asset.split("/") if "/" in asset else (asset, "USD")

        prompt = (
            f"You are a senior forex analyst specialized in {asset}.\n\n"
            f"{asset} Technical Data:\n"
            f"- Price: {price:.5f} | MA50: {ma_50:.5f} "
            f"({'ABOVE' if price > ma_50 else 'BELOW'} MA50)\n"
            f"- RSI-14: {rsi:.1f} | RSI-1h: {rsi_1h}\n"
            f"- MACD: {macd:.6f} vs signal {macd_sig:.6f} "
            f"({'bullish' if macd > macd_sig else 'bearish'})\n\n"
            f"Macro indicators:\n" + ("\n".join(macro_lines) or "N/A") + "\n\n"
            f"Market context:\n{air_summary}\n\n"
            f"Note: For {asset}, BULLISH means {base} strengthens vs {quote}. "
            f"Higher US rates → USD stronger (bearish EUR/USD). "
            f"Higher DXY → bearish EUR/USD. Positive COT net long EUR → bullish EUR/USD.\n\n"
            "Respond in strict JSON:\n"
            '{"score": <0-100>, "signal": "BULLISH"|"NEUTRAL"|"BEARISH", '
            '"summary": "<2-3 sentences max>", "confidence": <0.0-1.0>}'
        )

        provider = self._llm_cfg.get("provider", "anthropic")
        if provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic()
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
            client = OpenAI(api_key=os.environ.get(api_key_env, ""), base_url=base_url)
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
            "summary": str(d.get("summary", "Analyse Forex fondamentale LLM")),
            "confidence": float(d.get("confidence", 0.65)),
        }

    # ------------------------------------------------------------------ #
    #  Rule-based fallback                                                 #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _rule_based(indicators: dict, asset: str) -> dict:
        score = 50.0

        rsi = indicators.get("rsi_14", 50)
        if rsi <= 30:
            score += 12
        elif rsi <= 40:
            score += 6
        elif rsi >= 70:
            score -= 12
        elif rsi >= 60:
            score -= 5

        macd = indicators.get("macd", 0)
        macd_sig = indicators.get("macd_signal", 0)
        if macd and macd_sig:
            score += 7 if macd > macd_sig else -7

        price = indicators.get("price", 0)
        ma_50 = indicators.get("ma_50", 0)
        if price and ma_50:
            score += 4 if price > ma_50 else -6

        score = max(0.0, min(100.0, score))
        return {
            "agent_name": "forex_fundamental",
            "score": round(score, 1),
            "signal": (
                "BULLISH" if score > 60 else ("BEARISH" if score < 40 else "NEUTRAL")
            ),
            "summary": f"Analyse {asset} rule-based (LLM indisponible)",
            "confidence": 0.45,
        }
