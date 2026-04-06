"""
agents/eth_fundamental_agent.py — Fondamentaux spécifiques à Ethereum.

Sources (toutes gratuites / sans clé API, sauf ETHERSCAN_API_KEY optionnel) :
  - mempool.space : gas tracker
  - beaconcha.in  : staking yield, validator count
  - DefiLlama     : TVL global ETH + top protocols
  - Etherscan     : active addresses, transactions (clé optionnelle)
  - CoinGecko     : market data globale

Utilisé par FundamentalAgent si `agents.fundamental.provider == "eth_fundamental"`.
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger("zeitgeist.eth_fundamental")

_TIMEOUT = 10  # secondes par requête HTTP


def _get(url: str, headers: dict | None = None) -> dict | None:
    """GET JSON sans dépendance externe (urllib seulement)."""
    import urllib.request

    h = {"User-Agent": "atlas-trader/2.0", **(headers or {})}
    try:
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        logger.debug(f"ETH onchain GET {url[:60]}… → {exc}")
        return None


class EthFundamentalAgent:
    """
    Analyse fondamentale on-chain pour ETH/USDT.
    Interface identique à FundamentalAgent.analyze() → retourne un dict d'agent.
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
            onchain = self._fetch_onchain_metrics()
            llm_result = self._analyze_with_llm(indicators, air, onchain)
            blended_score = round(llm_result["score"] * 0.6 + rule_result["score"] * 0.4, 1)
            return {
                "agent_name": "eth_fundamental",
                "score": blended_score,
                "signal": (
                    "BULLISH" if blended_score > 60
                    else ("BEARISH" if blended_score < 40 else "NEUTRAL")
                ),
                "summary": llm_result["summary"],
                "confidence": round(
                    llm_result["confidence"] * 0.6 + rule_result["confidence"] * 0.4, 2
                ),
                "rule_score": rule_result["score"],
                "llm_score": llm_result["score"],
                "onchain": onchain,
            }
        except Exception as exc:
            logger.warning(f"EthFundamentalAgent LLM fallback (rules): {exc}")
            return rule_result

    # ------------------------------------------------------------------ #
    #  On-chain data collection                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _fetch_onchain_metrics() -> dict:
        """
        Collecte les métriques on-chain ETH depuis des APIs publiques.
        Retourne un dict avec les clés disponibles — aucune exception levée.
        """
        data: dict = {}

        # 1. Gas price moyen (mempool.space)
        r = _get("https://mempool.space/api/v1/fees/recommended")
        if r:
            data["gas_fast_gwei"] = float(r.get("fastestFee", 0))
            data["gas_med_gwei"] = float(r.get("halfHourFee", 0))

        # 2. Staking yield + validator count (beaconcha.in — public)
        r = _get("https://beaconcha.in/api/v1/ethstore/latest")
        if r and r.get("status") == "OK":
            dt = r.get("data", {})
            apr = dt.get("avgapr7d")
            if apr is not None:
                data["staking_apr_pct"] = float(apr) * 100
            validators = dt.get("validatorscount")
            if validators:
                data["active_validators"] = int(validators)

        # 3. TVL total ETH (DefiLlama — public, sans clé)
        r = _get("https://api.llama.fi/v2/chains")
        if isinstance(r, list):
            for chain in r:
                if str(chain.get("name", "")).lower() == "ethereum":
                    tvl = chain.get("tvl")
                    if tvl:
                        data["eth_defi_tvl_usd"] = float(tvl)
                    break

        # 4. Top protocoles DeFi sur ETH (DefiLlama)
        r = _get("https://api.llama.fi/protocols")
        if isinstance(r, list):
            eth_protocols = [
                p for p in r
                if "ethereum" in [c.lower() for c in (p.get("chains") or [])]
                and (p.get("tvl") or 0) > 100e6
            ]
            eth_protocols.sort(key=lambda p: p.get("tvl", 0), reverse=True)
            if eth_protocols:
                data["top_defi_protocols"] = [
                    {"name": p["name"], "tvl": p["tvl"]}
                    for p in eth_protocols[:5]
                ]

        # 5. Adresses actives + tx count (Etherscan, clé optionnelle)
        etherscan_key = os.environ.get("ETHERSCAN_API_KEY", "")
        if etherscan_key:
            r = _get(
                f"https://api.etherscan.io/api?module=stats&action=dailytx"
                f"&apikey={etherscan_key}"
            )
            if r and r.get("status") == "1":
                vals = r.get("result", [])
                if vals:
                    data["daily_tx_count"] = int(vals[-1].get("transactionCount", 0))

        # 6. Supply staked + burned  (beaconcha.in supply endpoint)
        r = _get("https://beaconcha.in/api/v1/execution/gasnow")
        if r and r.get("data"):
            dt = r["data"]
            rapid = dt.get("rapid")
            if rapid:
                data["gas_rapid_gwei"] = float(rapid) / 1e9

        # 7. Dominance ETH + global market cap (CoinGecko global)
        r = _get("https://api.coingecko.com/api/v3/global")
        if r and "data" in r:
            d = r["data"]
            eth_dom = d.get("market_cap_percentage", {}).get("eth")
            if eth_dom is not None:
                data["eth_dominance"] = float(eth_dom)

        return data

    # ------------------------------------------------------------------ #
    #  LLM analysis                                                        #
    # ------------------------------------------------------------------ #

    def _analyze_with_llm(self, indicators: dict, air: dict, onchain: dict) -> dict:
        price = indicators.get("price", 0)
        ma_50 = indicators.get("ma_50", 0)
        rsi = indicators.get("rsi_14", 50)
        macd = indicators.get("macd", 0)
        macd_sig = indicators.get("macd_signal", 0)
        funding = indicators.get("funding_rate", 0)
        volume = indicators.get("volume_24h", 0)
        rsi_1h = indicators.get("rsi_1h", "N/A")
        rsi_4h = indicators.get("rsi_4h", "N/A")

        # On-chain summary
        oc_lines = []
        if "gas_fast_gwei" in onchain:
            oc_lines.append(f"- Gas fast: {onchain['gas_fast_gwei']:.0f} gwei")
        if "staking_apr_pct" in onchain:
            oc_lines.append(f"- Staking APR: {onchain['staking_apr_pct']:.2f}%")
        if "active_validators" in onchain:
            oc_lines.append(f"- Active validators: {onchain['active_validators']:,}")
        if "eth_defi_tvl_usd" in onchain:
            oc_lines.append(f"- ETH DeFi TVL: ${onchain['eth_defi_tvl_usd']/1e9:.1f}B")
        if "eth_dominance" in onchain:
            oc_lines.append(f"- ETH dominance: {onchain['eth_dominance']:.1f}%")
        if "daily_tx_count" in onchain:
            oc_lines.append(f"- Daily tx count: {onchain['daily_tx_count']:,}")
        if "top_defi_protocols" in onchain:
            tops = ", ".join(
                f"{p['name']}(${p['tvl']/1e9:.1f}B)"
                for p in onchain["top_defi_protocols"][:3]
            )
            oc_lines.append(f"- Top DeFi: {tops}")

        air_summary = (air.get("summary", "N/A") or "N/A")[:300]

        prompt = (
            "You are a senior Ethereum analyst. Analyze these ETH fundamentals and provide "
            "a conviction score [0-100].\n\n"
            f"ETH Market Data:\n"
            f"- Price: ${price:,.0f} | MA50: ${ma_50:,.0f} "
            f"({'ABOVE' if price > ma_50 else 'BELOW'} MA50)\n"
            f"- RSI-14: {rsi:.1f} | RSI-1h: {rsi_1h} | RSI-4h: {rsi_4h}\n"
            f"- MACD: {macd:.4f} vs signal {macd_sig:.4f} "
            f"({'bullish' if macd > macd_sig else 'bearish'})\n"
            f"- Funding rate: {funding:.5f}\n"
            f"- 24h Volume: ${volume/1e9:.2f}B\n\n"
            f"ETH On-chain & DeFi:\n" + "\n".join(oc_lines) + "\n\n"
            f"Macro context:\n{air_summary}\n\n"
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
        data = json.loads(raw[json_start:json_end])
        score = float(data.get("score", 50))
        signal = str(data.get("signal", "NEUTRAL")).upper()
        if signal not in ("BULLISH", "BEARISH", "NEUTRAL"):
            signal = "BULLISH" if score > 60 else ("BEARISH" if score < 40 else "NEUTRAL")
        return {
            "score": round(score, 1),
            "signal": signal,
            "summary": str(data.get("summary", "Analyse ETH fondamentale LLM")),
            "confidence": float(data.get("confidence", 0.7)),
        }

    # ------------------------------------------------------------------ #
    #  Rule-based fallback                                                 #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _rule_based(indicators: dict) -> dict:
        """Scoring rule-based ETH (backup si LLM indisponible)."""
        score = 50.0

        funding = indicators.get("funding_rate", 0)
        if funding < -0.005:
            score += 15
        elif funding < 0:
            score += 5
        elif funding > 0.02:
            score -= 15
        elif funding > 0.005:
            score -= 5

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
            if (macd - macd_sig) > 0 and macd > 0:
                score += 8
            elif (macd - macd_sig) < 0 and macd < 0:
                score -= 8

        price = indicators.get("price", 0)
        ma_50 = indicators.get("ma_50", 0)
        if price and ma_50:
            score += 3 if price > ma_50 else -7

        score = max(0.0, min(100.0, score))
        return {
            "agent_name": "eth_fundamental",
            "score": round(score, 1),
            "signal": (
                "BULLISH" if score > 60 else ("BEARISH" if score < 40 else "NEUTRAL")
            ),
            "summary": "Analyse ETH rule-based (LLM indisponible)",
            "confidence": 0.55,
        }
