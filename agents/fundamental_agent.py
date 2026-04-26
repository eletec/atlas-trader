"""
agents/fundamental_agent.py — Analyse des fondamentaux avec interpretation LLM contextuelle.
Envoie les indicateurs + contexte macro a Claude Haiku pour une analyse relative
qui tient compte du contexte (RSI 65 apres correction != RSI 65 sur ATH).
"""
from __future__ import annotations
import json
import logging

logger = logging.getLogger("zeitgeist.fundamental")


class FundamentalAgent:
    """Analyse les fondamentaux on-chain et macro avec interpretation LLM."""

    _climate_cache: dict = {}  # cache module-level partagé entre instances (TTL 24h)

    def __init__(self):
        from utils.config import load_settings
        cfg = load_settings()
        self._llm_cfg = cfg.get("llm", {})

    def analyze(self, state: dict) -> dict:
        """Retourne une analyse fondamentale enrichie par LLM."""
        indicators = state.get("market_indicators", {}) or {}
        rule_result = self._rule_based(indicators)

        # CA2: mode agentique si activé dans settings.yaml
        if self._llm_cfg.get("provider", "anthropic") == "anthropic":
            from utils.config import load_settings as _ls
            _fund_cfg = _ls().get("agents", {}).get("fundamental", {})
            if _fund_cfg.get("agentic", False):
                try:
                    return self._analyze_agentic(state)
                except Exception as exc:
                    logger.warning("CA2: agentic fallback rule_based (%s)", exc)
                    return rule_result

        # Tentative d'enrichissement LLM
        air = state.get("air_du_temps") or {}
        asset = state.get("asset", "BTC/USDT")
        try:
            llm_result = self._analyze_with_llm(indicators, air, asset=asset)
            # Fusion : score moyen pondere (LLM 60%, rules 40%)
            blended_score = round(llm_result["score"] * 0.6 + rule_result["score"] * 0.4, 1)
            return {
                "agent_name": "fundamental",
                "score": blended_score,
                "signal": (
                    "BULLISH" if blended_score > 60
                    else ("BEARISH" if blended_score < 40 else "NEUTRAL")
                ),
                "summary": llm_result["summary"],
                "confidence": round(
                    (llm_result["confidence"] * 0.6 + rule_result["confidence"] * 0.4), 2
                ),
                "rule_score": rule_result["score"],
                "llm_score": llm_result["score"],
            }
        except Exception as exc:
            logger.warning(f"FundamentalAgent LLM fallback (rules): {exc}")
            return rule_result

    def _analyze_with_llm(self, indicators: dict, air: dict, asset: str = "BTC/USDT") -> dict:
        """Appel Claude Haiku : interpretation contextuelle des indicateurs."""
        price = indicators.get("price", 0)
        ma_50 = indicators.get("ma_50", 0)
        rsi = indicators.get("rsi_14", 50)
        macd = indicators.get("macd", 0)
        macd_signal = indicators.get("macd_signal", 0)
        funding = indicators.get("funding_rate", 0)
        volume = indicators.get("volume_24h", 0)
        bb_upper = indicators.get("bb_upper", 0)
        bb_lower = indicators.get("bb_lower", 0)
        rsi_1h = indicators.get("rsi_1h", "N/A")
        rsi_4h = indicators.get("rsi_4h", "N/A")
        trend_4h = indicators.get("trend_4h", "N/A")

        # Bollinger position
        bb_pct = "N/A"
        if bb_upper and bb_lower and bb_upper > bb_lower:
            bb_pct = f"{(price - bb_lower) / (bb_upper - bb_lower):.0%}"

        air_summary = air.get("summary", "Non disponible")[:300] if air else "Non disponible"

        # On-chain metrics (best-effort, graceful fallback)
        onchain = self._fetch_onchain_metrics()
        onchain_block = ""
        if onchain:
            parts = []
            if "active_addresses" in onchain:
                parts.append(f"- Active addresses (5d avg): {onchain['active_addresses']:,}")
            if "hashrate_eh" in onchain:
                parts.append(f"- Hashrate: {onchain['hashrate_eh']:.1f} EH/s")
            if "btc_dominance" in onchain:
                parts.append(f"- BTC dominance: {onchain['btc_dominance']:.1f}%")
            if "total_market_cap_usd" in onchain:
                parts.append(f"- Total crypto market cap: ${onchain['total_market_cap_usd']/1e12:.2f}T")
            if parts:
                onchain_block = "\nOn-chain metrics:\n" + "\n".join(parts)

        # Climate context — pertinent uniquement pour WTI/USD et EUR/USD
        climate_block = ""
        if asset in ("WTI/USD", "EUR/USD"):
            climate_ctx = self._fetch_climate_context()
            if climate_ctx:
                climate_block = f"\nClimate context:\n- {climate_ctx}\n"

        asset_label = asset.replace("/", "")
        prompt = (
            f"You are a senior {asset_label} analyst. Analyze the indicators and give "
            "a conviction score [0-100].\n\n"
            f"{asset_label} Indicators:\n"
            f"- Price: ${price:,.0f} | MA50: ${ma_50:,.0f} "
            f"({'ABOVE' if price > ma_50 else 'BELOW'} MA50)\n"
            f"- RSI-14 (15m): {rsi:.1f} | RSI-1h: {rsi_1h} | RSI-4h: {rsi_4h}\n"
            f"- 4h Trend: {trend_4h}\n"
            f"- MACD: {macd:.4f} vs signal {macd_signal:.4f} "
            f"({'bullish' if macd > macd_signal else 'bearish'})\n"
            f"- Funding rate: {funding:.5f}\n"
            f"- 24h Volume: ${volume/1e9:.2f}B\n"
            f"- Bollinger position: {bb_pct}\n"
            f"{onchain_block}\n"
            f"{climate_block}"
            f"Macro context:\n{air_summary}\n\n"
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
            import os
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
        data = json.loads(raw[json_start:json_end])
        score = float(data.get("score", 50))
        signal = str(data.get("signal", "NEUTRAL")).upper()
        if signal not in ("BULLISH", "BEARISH", "NEUTRAL"):
            signal = "BULLISH" if score > 60 else ("BEARISH" if score < 40 else "NEUTRAL")
        return {
            "score": round(score, 1),
            "signal": signal,
            "summary": str(data.get("summary", "Analyse fondamentale LLM")),
            "confidence": float(data.get("confidence", 0.7)),
        }

    @staticmethod
    def _fetch_onchain_metrics() -> dict:
        """
        Collecte les m\u00e9triques on-chain depuis des APIs publiques gratuites.
        Aucune cl\u00e9 API requise (sauf Dune si DUNE_API_KEY est pr\u00e9sent).
        Timeout de 10s par requ\u00eate ; \u00e9checs ignor\u00e9s silencieusement.
        """
        import urllib.request
        import json as _json

        data: dict = {}
        _TIMEOUT = 10

        def _get(url: str) -> dict | None:
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "zeitgeist-trader/1.0"}
                )
                with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                    return _json.loads(resp.read().decode())
            except Exception:
                return None

        # 1. Adresses actives Bitcoin \u2014 blockchain.info (public, sans cl\u00e9)
        r = _get(
            "https://api.blockchain.info/charts/n-unique-addresses"
            "?timespan=5days&format=json"
        )
        if r and isinstance(r.get("values"), list) and r["values"]:
            vals = [v.get("y", 0) for v in r["values"] if v.get("y")]
            if vals:
                data["active_addresses"] = int(sum(vals) / len(vals))

        # 2. Hashrate Bitcoin \u2014 mempool.space (public, sans cl\u00e9)
        r = _get("https://mempool.space/api/v1/mining/hashrate/3d")
        if r:
            # L'API retourne {"hashrates": [{..., "avgHashrate": ...}], "difficulty": [...]}
            hrs = r.get("hashrates", [])
            if hrs:
                latest_hr = hrs[-1].get("avgHashrate", 0)
                if latest_hr:
                    data["hashrate_eh"] = float(latest_hr) / 1e18  # en EH/s

        # 3. Dominance BTC + market cap global \u2014 CoinGecko (public, limit\u00e9 ~30 req/min)
        r = _get("https://api.coingecko.com/api/v3/global")
        if r and "data" in r:
            d = r["data"]
            dom = d.get("market_cap_percentage", {}).get("btc")
            if dom is not None:
                data["btc_dominance"] = float(dom)
            total_mc = d.get("total_market_cap", {}).get("usd")
            if total_mc is not None:
                data["total_market_cap_usd"] = float(total_mc)

        return data

    @staticmethod
    def _fetch_climate_context() -> str:
        """
        Retourne l'anomalie de température globale NASA GISTEMP v4 sous forme
        de chaîne descriptive.

        Stratégie de résilience (3 niveaux) :
          1. Cache mémoire (TTL 24h) — pas de I/O du tout
          2. Fichier local  storage/gistemp_v4.csv  — mis à jour à chaque
             download réussi ; utilisé comme fallback si NASA est hors ligne.
             Les données historiques GISTEMP sont immutables (seul le dernier
             point évolue) : un fichier de plusieurs semaines reste valide.
          3. Download depuis data.giss.nasa.gov — tenté seulement si le cache
             mémoire est expiré.
        """
        import time
        import csv
        import io
        import urllib.request
        from pathlib import Path

        _KEY = "gistemp_v4"
        _MEM_TTL = 86400        # 24 h — ne pas re-télécharger avant
        _LOCAL_PATH = Path(__file__).resolve().parent.parent / "storage" / "gistemp_v4.csv"
        _URL = "https://data.giss.nasa.gov/gistemp/tabledata_v4/GLB.Ts+dSST.csv"

        cache = FundamentalAgent._climate_cache

        # ── 1. Cache mémoire ─────────────────────────────────────────────
        entry = cache.get(_KEY)
        if entry and (time.time() - entry["ts"]) < _MEM_TTL:
            return entry["value"]

        # ── Helpers ───────────────────────────────────────────────────────
        def _parse(raw_text: str) -> str:
            """Parse le CSV GISTEMP et retourne la chaîne descriptive."""
            months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            rows = []
            reader = csv.reader(io.StringIO(raw_text))
            for row in reader:
                if row and row[0].strip().lstrip("-").isdigit():
                    rows.append(row)
            if not rows:
                raise ValueError("GISTEMP: aucune ligne de données")

            last = rows[-1]
            year = last[0].strip()
            annual = last[13].strip() if len(last) > 13 else "***"

            last_month_name, last_month_val = "N/A", "***"
            for i, m in enumerate(months):
                val = last[i + 1].strip() if len(last) > i + 1 else "***"
                if val != "***":
                    last_month_name, last_month_val = m, val

            if annual != "***":
                anomaly_val = float(annual)
                period = f"{year} annual"
            elif last_month_val != "***":
                anomaly_val = float(last_month_val)
                period = f"{year}-{last_month_name}"
            else:
                raise ValueError("GISTEMP: toutes les valeurs manquantes")

            sign = "+" if anomaly_val >= 0 else ""
            if anomaly_val >= 1.0:
                interp = "significantly above baseline — warm conditions bearish energy demand (WTI↓)"
            elif anomaly_val >= 0.5:
                interp = "above baseline — mild conditions, moderate impact on energy demand"
            elif anomaly_val >= 0.0:
                interp = "slightly above baseline — near-normal conditions"
            else:
                interp = "below baseline — colder than normal, supportive energy demand (WTI↑)"

            return (
                f"NASA GISTEMP v4 ({period}): {sign}{anomaly_val:.2f}°C vs "
                f"1951-1980 baseline — {interp}"
            )

        # ── 2. Tenter le download réseau ─────────────────────────────────
        raw_from_network: str | None = None
        try:
            req = urllib.request.Request(_URL, headers={"User-Agent": "zeitgeist-trader/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw_from_network = resp.read().decode("utf-8", errors="ignore")

            result = _parse(raw_from_network)
            logger.info("GISTEMP v4 fetched from NASA: %s", result)

            # Persister localement pour les futurs fallbacks
            try:
                _LOCAL_PATH.parent.mkdir(parents=True, exist_ok=True)
                _LOCAL_PATH.write_text(raw_from_network, encoding="utf-8")
                logger.debug("GISTEMP v4 saved to %s", _LOCAL_PATH)
            except Exception as save_exc:
                logger.debug("GISTEMP v4 local save failed (non-bloquant): %s", save_exc)

        except Exception as net_exc:
            logger.warning("GISTEMP v4 network unavailable (%s) — trying local cache", net_exc)

            # ── 3. Fallback fichier local ─────────────────────────────────
            result = ""
            if _LOCAL_PATH.exists():
                try:
                    raw_local = _LOCAL_PATH.read_text(encoding="utf-8")
                    result = _parse(raw_local)
                    age_days = (time.time() - _LOCAL_PATH.stat().st_mtime) / 86400
                    logger.info(
                        "GISTEMP v4 loaded from local cache (%.0f days old): %s",
                        age_days, result,
                    )
                except Exception as local_exc:
                    logger.debug("GISTEMP v4 local parse failed: %s", local_exc)
            else:
                logger.debug("GISTEMP v4: aucun fichier local disponible")

        # ── Mettre en cache mémoire ───────────────────────────────────────
        cache[_KEY] = {"ts": time.time(), "value": result}
        return result

    @staticmethod
    def _rule_based(indicators: dict) -> dict:
        """Scoring rule-based original (backup si LLM indisponible)."""
        score = 50.0
        signals = []

        funding = indicators.get("funding_rate", 0)
        if funding < -0.005:
            score += 15
            signals.append(f"Funding negatif ({funding:.4f})")
        elif funding < 0:
            score += 5
        elif funding > 0.02:
            score -= 15
            signals.append(f"Funding eleve ({funding:.4f})")
        elif funding > 0.005:
            score -= 5

        rsi = indicators.get("rsi_14", 50)
        if rsi <= 30:
            score += 15
            signals.append(f"RSI survente ({rsi:.0f})")
        elif rsi <= 40:
            score += 8
        elif rsi >= 70:
            score -= 15
            signals.append(f"RSI surachat ({rsi:.0f})")
        elif rsi >= 60:
            score -= 5

        macd = indicators.get("macd", 0)
        macd_signal_val = indicators.get("macd_signal", 0)
        if macd and macd_signal_val:
            if (macd - macd_signal_val) > 0 and macd > 0:
                score += 8
                signals.append("MACD haussier")
            elif (macd - macd_signal_val) < 0 and macd < 0:
                score -= 8
                signals.append("MACD baissier")

        price = indicators.get("price", 0)
        ma_50 = indicators.get("ma_50", 0)
        if price and ma_50:
            pct_from_ma50 = (price - ma_50) / ma_50 * 100
            if pct_from_ma50 > 0:
                score += 3
            else:
                score -= 7

        bb_upper = indicators.get("bb_upper", 0)
        bb_lower = indicators.get("bb_lower", 0)
        if price and bb_upper and bb_lower and bb_upper > bb_lower:
            bb_pos = (price - bb_lower) / (bb_upper - bb_lower)
            if bb_pos < 0.15:
                score += 8
                signals.append(f"Proche bande basse BB ({bb_pos:.0%})")
            elif bb_pos > 0.85:
                score -= 8
                signals.append(f"Proche bande haute BB ({bb_pos:.0%})")

        volume = indicators.get("volume_24h", 0)
        if volume > 3e9:
            score += 5
        elif volume > 1.5e9:
            score += 3

        score = max(0, min(100, score))
        signal = "BULLISH" if score > 60 else ("BEARISH" if score < 40 else "NEUTRAL")
        return {
            "agent_name": "fundamental",
            "score": round(score, 1),
            "signal": signal,
            "summary": " | ".join(signals) if signals else "Fondamentaux neutres",
            "confidence": 0.7,
        }

    # ------------------------------------------------------------------
    # CA2 — Agentic mode : FundamentalAgent as true Claude sub-agent
    # Activated when settings.yaml > agents.fundamental.agentic: true
    # ------------------------------------------------------------------

    def _analyze_agentic(self, state: dict) -> dict:
        """
        Variante agentique : Claude décide lui-même quelles données collecter
        via tool_use (get_market_indicators et get_onchain_data).
        Retourne un dict compatible avec analyze().
        """
        try:
            import anthropic
        except ImportError:
            logger.warning("CA2: anthropic non disponible — fallback rule_based")
            return self._rule_based(state.get("market_indicators", {}))

        client = anthropic.Anthropic(timeout=60.0)
        model = self._llm_cfg.get("haiku_model", "claude-3-5-haiku-20241022")

        tools = [
            {
                "name": "get_market_indicators",
                "description": (
                    "Retourne les indicateurs techniques BTC : "
                    "price, rsi_14, rsi_1h, rsi_4h, macd, funding_rate, "
                    "bb_upper, bb_lower, volume_24h, trend_4h."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "ex: BTC/USDT"},
                    },
                    "required": ["symbol"],
                },
            },
            {
                "name": "get_onchain_data",
                "description": (
                    "Retourne des métriques on-chain BTC : "
                    "net_exchange_flow (BTC), sopr, active_addresses_24h."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                    },
                    "required": ["symbol"],
                },
            },
        ]

        asset = state.get("asset", "BTC/USDT")

        # Inject climate context for energy/FX assets before agentic prompt
        climate_suffix = ""
        if asset in ("WTI/USD", "EUR/USD"):
            climate_ctx = self._fetch_climate_context()
            if climate_ctx:
                climate_suffix = f"\n\nAdditional context: {climate_ctx}"

        messages = [
            {
                "role": "user",
                "content": (
                    f"Analyze the fundamentals of {asset}. "
                    "Use the available tools to collect data, then "
                    "return a JSON with: score (int 0-100), signal (BULLISH/BEARISH/NEUTRAL), "
                    f"summary (str), confidence (float 0-1).{climate_suffix}"
                ),
            }
        ]

        max_iterations = 4
        for _ in range(max_iterations):
            response = client.messages.create(
                model=model,
                max_tokens=512,
                tools=tools,
                messages=messages,
                system=(
                    "You are an expert crypto analyst. "
                    "Use the tools to collect the necessary data "
                    "before returning your final analysis. "
                    "Respond in strict JSON (no markdown)."
                ),
            )

            if response.stop_reason == "end_turn":
                break

            if response.stop_reason == "tool_use":
                tool_calls = [b for b in response.content if b.type == "tool_use"]
                tool_results = []
                for call in tool_calls:
                    result_data = self._handle_tool_call(call.name, call.input, state)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": json.dumps(result_data),
                    })
                messages = messages + [
                    {"role": "assistant", "content": response.content},
                    {"role": "user", "content": tool_results},
                ]
            else:
                break

        # Extraire le texte final
        raw = "".join(
            b.text for b in response.content if getattr(b, "type", "") == "text"
        ).strip()

        parsed = self._parse_agentic_json(raw)
        score = float(parsed.get("score", 50))
        signal = parsed.get("signal", "NEUTRAL")
        summary = parsed.get("summary", "Analyse agentique")
        confidence = float(parsed.get("confidence", 0.75))

        tokens = 0
        if hasattr(response, "usage"):
            tokens = getattr(response.usage, "input_tokens", 0) + getattr(response.usage, "output_tokens", 0)

        return {
            "agent_name": "fundamental",
            "score": round(score, 1),
            "signal": signal,
            "summary": summary,
            "confidence": confidence,
            "tokens_used": tokens,
            "agentic": True,
        }

    def _handle_tool_call(self, tool_name: str, tool_input: dict, state: dict) -> dict:
        """Exécute le tool demandé par Claude et retourne les données."""
        if tool_name == "get_market_indicators":
            indicators = state.get("market_indicators", {}) or {}
            return {k: v for k, v in indicators.items()
                    if k in ("price", "rsi_14", "rsi_1h", "rsi_4h", "macd", "macd_signal",
                              "funding_rate", "bb_upper", "bb_lower", "volume_24h", "trend_4h")}
        if tool_name == "get_onchain_data":
            try:
                from agents.onchain_agent import OnChainAgent
                onchain_result = OnChainAgent().analyze(state)
                return onchain_result.get("raw_data", {})
            except Exception as exc:
                logger.debug("CA2: onchain tool failed: %s", exc)
                return {"error": str(exc)}
        return {"error": f"Outil inconnu : {tool_name}"}

    @staticmethod
    def _parse_agentic_json(raw: str) -> dict:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rstrip("`").strip()
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            try:
                return json.loads(raw[start:end])
            except json.JSONDecodeError:
                pass
        return {}
