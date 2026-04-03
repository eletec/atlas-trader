"""
agents/onchain_agent.py — Données on-chain BTC via APIs publiques.

Sources GRATUITES sans clé :
  - blockchain.com /stats       → trade_volume_btc proxy, n_tx, hash_rate
  - blockchain.com /q/24hraddr  → adresses actives 24h
  - mempool.space  /api/mempool → congestion + fees live (le plus réactif)
  - CoinMetrics Community API   → SOPR + AdrActCnt (tier gratuit officiel)

Sources optionnelles avec clé GRATUITE (inscription requise) :
  - CryptoQuant free tier (CRYPTOQUANT_API_KEY)
    → exchange net flow BTC exact (entrées/sorties exchanges)
    → 50 req/jour max, résolution 1 jour, historique 7 jours, usage personnel
    → résultat mis en cache 24h (storage/cryptoquant_cache.json) pour préserver le quota
    → inscription : https://cryptoquant.com/settings/api
  - Glassnode (GLASSNODE_API_KEY)
    → plan payant requis (Advanced ~$29/mois), studio = PAS d'API
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("zeitgeist.onchain")

# Sources gratuites (sans clé)
_BLOCKCHAIN_STATS = "https://api.blockchain.info/stats"
_BLOCKCHAIN_API   = "https://api.blockchain.info"
_MEMPOOL_API      = "https://mempool.space/api"
_COINMETRICS_API  = "https://community-api.coinmetrics.io/v4"

# Sources optionnelles (clé gratuite ou payante)
_CRYPTOQUANT_API  = "https://api.cryptoquant.com/v1"
_GLASSNODE_BASE   = "https://api.glassnode.com/v1/metrics"

# Cache fichier pour CryptoQuant (50 req/jour — résolution 1 jour)
_CQ_CACHE_PATH = (
    __import__("pathlib").Path(__file__).resolve().parent.parent
    / "storage" / "cryptoquant_cache.json"
)


class OnChainAgent:
    """Signal on-chain BTC — sources gratuites sans clé API."""

    def analyze(self, state: dict) -> dict:
        """Retourne un score basé sur les données on-chain."""
        # --- Collecte des métriques ---
        net_flow     = self._get_net_exchange_flow()      # CryptoQuant free (clé gratuite)
        stats        = self._get_blockchain_stats()       # blockchain.com (sans clé)
        mempool      = self._get_mempool_stats()          # mempool.space (sans clé)
        active_addr  = self._get_active_addresses()       # CoinMetrics/blockchain.com
        sopr         = self._get_sopr()                   # CoinMetrics Community

        score = 50.0
        signals = []

        # --- 1. Exchange net flow (CryptoQuant — le plus précis) ---
        if net_flow is not None:
            if net_flow < -5_000:
                score += 15
                signals.append(f"Sortie massive exchanges ({net_flow:+,.0f} BTC) — accumulation")
            elif net_flow < -1_000:
                score += 8
                signals.append(f"Sorties exchanges ({net_flow:+,.0f} BTC) — accumulation modérée")
            elif net_flow > 5_000:
                score -= 15
                signals.append(f"Entrée massive exchanges ({net_flow:+,.0f} BTC) — distribution")
            elif net_flow > 1_000:
                score -= 8
                signals.append(f"Entrées exchanges ({net_flow:+,.0f} BTC) — pression vendeuse")
            else:
                signals.append(f"Exchange flow neutre ({net_flow:+,.0f} BTC)")

        # --- 2. Exchange volume proxy blockchain.com (si CryptoQuant indispo) ---
        trade_vol = stats.get("trade_volume_btc") if stats else None
        if trade_vol is not None and net_flow is None:
            # Fallback : volume total échangé comme proxy d'activité
            if trade_vol < 15_000:
                score += 6
                signals.append(f"Volume exchange faible ({trade_vol:,.0f} BTC) — accumulation probable")
            elif trade_vol > 60_000:
                score -= 8
                signals.append(f"Volume exchange élevé ({trade_vol:,.0f} BTC) — pression vendeuse")
            else:
                signals.append(f"Volume exchange normal ({trade_vol:,.0f} BTC)")

        # --- 3. Fee pressure mempool.space ---
        pending_txs = mempool.get("count") if mempool else None
        total_fees  = mempool.get("total_fee") if mempool else None   # satoshis
        if pending_txs is not None:
            if pending_txs > 80_000:
                # Mempool surchargé = forte demande réseau = bullish sentiment
                score += 6
                signals.append(f"Mempool congestionné ({pending_txs:,} txs) — forte demande")
            elif pending_txs < 5_000:
                score -= 3
                signals.append(f"Mempool calme ({pending_txs:,} txs)")
            else:
                signals.append(f"Mempool normal ({pending_txs:,} txs)")

        # --- 3. Adresses actives 24h ---
        if active_addr is not None:
            if active_addr > 1_000_000:
                score += 5
                signals.append(f"Réseau très actif ({active_addr:,} adresses/j)")
            elif active_addr > 700_000:
                score += 2
                signals.append(f"Activité réseau normale ({active_addr:,} adresses/j)")
            else:
                score -= 3
                signals.append(f"Activité réseau faible ({active_addr:,} adresses/j)")

        # --- 4. SOPR (CoinMetrics community ou Glassnode payant) ---
        if sopr is not None:
            if sopr < 0.98:
                score += 12
                signals.append(f"SOPR < 1 ({sopr:.3f}) — capitulation, plancher potentiel")
            elif sopr < 1.0:
                score += 5
                signals.append(f"SOPR légèrement négatif ({sopr:.3f})")
            elif sopr > 1.05:
                score -= 10
                signals.append(f"SOPR élevé ({sopr:.3f}) — distribution de profits")
            elif sopr > 1.01:
                score -= 4
                signals.append(f"SOPR positif ({sopr:.3f}) — prises de bénéfices")
            else:
                signals.append(f"SOPR neutre ({sopr:.3f})")

        # --- 5. Transaction count (blockchain.info) ---
        n_tx = stats.get("n_tx") if stats else None
        if n_tx is not None:
            if n_tx > 400_000:
                score += 3
                signals.append(f"Nb transactions élevé ({n_tx:,}/j)")
            elif n_tx < 200_000:
                score -= 2
                signals.append(f"Faible activité transactions ({n_tx:,}/j)")

        score = max(0, min(100, score))
        signal = "BULLISH" if score > 60 else ("BEARISH" if score < 40 else "NEUTRAL")
        n_sources = sum(x is not None for x in [net_flow, trade_vol, pending_txs, active_addr, sopr])
        confidence = round(min(0.9, 0.2 + 0.14 * n_sources), 2)

        logger.debug("OnChain score=%.0f net_flow=%s SOPR=%s pending_txs=%s",
                     score, net_flow, sopr, pending_txs)
        return {
            "agent_name": "onchain",
            "score": round(score, 1),
            "signal": signal,
            "summary": " | ".join(signals) if signals else "Données on-chain indisponibles",
            "confidence": confidence,
            "net_exchange_flow_btc": net_flow,
            "sopr": sopr,
            "active_addresses": active_addr,
            "trade_volume_btc": trade_vol,
            "mempool_pending_txs": pending_txs,
            "raw_data": {
                "net_exchange_flow_btc": net_flow,
                "sopr": sopr,
                "active_addresses": active_addr,
                "trade_volume_btc": trade_vol,
                "mempool_pending_txs": pending_txs,
                "n_tx_24h": n_tx,
            },
        }

    # ------------------------------------------------------------------
    # Sources gratuites — aucune clé requise
    # ------------------------------------------------------------------

    @staticmethod
    def _get_net_exchange_flow() -> float | None:
        """
        Exchange net flow BTC (entrées - sorties exchanges).
        Source : CryptoQuant free tier.
        Plan gratuit : 50 req/jour, résolution 1 jour, 7 jours d'historique, usage personnel.
        ⇒ Résultat mis en cache 24h dans storage/cryptoquant_cache.json
           pour ne pas épuiser le quota sur ~96 cycles/jour.
        """
        import json
        from datetime import datetime, timezone, timedelta

        api_key = os.environ.get("CRYPTOQUANT_API_KEY", "")
        if not api_key:
            return None

        # Lire le cache (TTL 23h pour rester sous les 50 req/jour)
        try:
            _CQ_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            if _CQ_CACHE_PATH.exists():
                cached = json.loads(_CQ_CACHE_PATH.read_text())
                cached_at = datetime.fromisoformat(cached["cached_at"])
                age = datetime.now(timezone.utc) - cached_at
                if age < timedelta(hours=23):
                    logger.debug("CryptoQuant net_flow depuis cache (age=%s)", age)
                    return cached.get("netflow")
        except Exception:
            pass

        try:
            from utils.http_session import get_http_session
            resp = get_http_session().get(
                f"{_CRYPTOQUANT_API}/btc/exchange-flows/netflow",
                params={"window": "day", "limit": 1},
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json().get("result", {}).get("data", [])
            value = round(float(data[0].get("netflow_total", 0)), 0) if data else None
            # Persister en cache
            try:
                _CQ_CACHE_PATH.write_text(
                    json.dumps({"netflow": value, "cached_at": datetime.now(timezone.utc).isoformat()})
                )
            except Exception:
                pass
            return value
        except Exception as exc:
            logger.debug("CryptoQuant net_flow indisponible: %s", exc)
        return None

    @staticmethod
    def _get_blockchain_stats() -> dict | None:
        """
        blockchain.info/stats — retourne trade_volume_btc, n_tx, hash_rate.
        Totalement gratuit, pas de clé.
        """
        try:
            from utils.http_session import get_http_session
            resp = get_http_session().get(_BLOCKCHAIN_STATS, timeout=6)
            resp.raise_for_status()
            data = resp.json()
            return {
                "trade_volume_btc": float(data.get("trade_volume_btc", 0) or 0),
                "n_tx":             int(data.get("n_tx", 0) or 0),
                "estimated_btc_sent": float(data.get("estimated_btc_sent", 0) or 0) / 1e8,
                "hash_rate":        float(data.get("hash_rate", 0) or 0),
            }
        except Exception as exc:
            logger.debug("blockchain.info/stats indisponible: %s", exc)
        return None

    @staticmethod
    def _get_mempool_stats() -> dict | None:
        """
        mempool.space/api/mempool — pending txs + total fees.
        Totalement gratuit, pas de clé.
        """
        try:
            from utils.http_session import get_http_session
            resp = get_http_session().get(f"{_MEMPOOL_API}/mempool", timeout=6)
            resp.raise_for_status()
            data = resp.json()
            return {
                "count":     int(data.get("count", 0)),
                "vsize":     int(data.get("vsize", 0)),
                "total_fee": int(data.get("total_fee", 0)),   # satoshis
            }
        except Exception as exc:
            logger.debug("mempool.space indisponible: %s", exc)
        return None

    @staticmethod
    def _get_active_addresses() -> int | None:
        """
        Adresses actives BTC (24h).
        Source : CoinMetrics Community (tier gratuit) → fallback blockchain.info.
        """
        # Tentative CoinMetrics community (gratuit, pas de clé)
        try:
            from utils.http_session import get_http_session
            resp = get_http_session().get(
                f"{_COINMETRICS_API}/timeseries/asset-metrics",
                params={"assets": "btc", "metrics": "AdrActCnt", "limit": 1,
                        "page_size": 1, "sort": "descending"},
                timeout=8,
            )
            if resp.status_code == 200:
                rows = resp.json().get("data", [])
                if rows and rows[0].get("AdrActCnt"):
                    return int(float(rows[0]["AdrActCnt"]))
        except Exception as exc:
            logger.debug("CoinMetrics AdrActCnt indisponible: %s", exc)

        # Fallback : blockchain.info (gratuit, pas de clé)
        try:
            from utils.http_session import get_http_session
            resp = get_http_session().get(f"{_BLOCKCHAIN_API}/q/24hraddr", timeout=6)
            resp.raise_for_status()
            return int(resp.text.strip())
        except Exception as exc:
            logger.debug("blockchain.info/q/24hraddr indisponible: %s", exc)
        return None

    @staticmethod
    def _get_sopr() -> float | None:
        """
        SOPR (Spent Output Profit Ratio).

        Ordre de priorité :
        1. CoinMetrics Community (gratuit, pas de clé) — résolution quotidienne
        2. Glassnode API (GLASSNODE_API_KEY) — si clé présente (plan PAYANT requis)
           /!\\ Le plan gratuit Glassnode Studio NE donne PAS accès à l'API.
        """
        # 1. CoinMetrics Community (gratuit)
        try:
            from utils.http_session import get_http_session
            resp = get_http_session().get(
                f"{_COINMETRICS_API}/timeseries/asset-metrics",
                params={"assets": "btc", "metrics": "sopr", "limit": 1,
                        "page_size": 1, "sort": "descending"},
                timeout=8,
            )
            if resp.status_code == 200:
                rows = resp.json().get("data", [])
                if rows and rows[0].get("sopr"):
                    return round(float(rows[0]["sopr"]), 4)
        except Exception as exc:
            logger.debug("CoinMetrics SOPR indisponible: %s", exc)

        # 2. Glassnode (optionnel — plan payant uniquement)
        api_key = os.environ.get("GLASSNODE_API_KEY", "")
        if api_key:
            try:
                from utils.http_session import get_http_session
                resp = get_http_session().get(
                    f"{_GLASSNODE_BASE}/indicators/sopr",
                    params={"a": "BTC", "i": "24h", "api_key": api_key},
                    timeout=8,
                )
                resp.raise_for_status()
                data = resp.json()
                if data:
                    return round(float(data[-1]["v"]), 4)
            except Exception as exc:
                logger.debug("Glassnode SOPR indisponible: %s", exc)

        return None
