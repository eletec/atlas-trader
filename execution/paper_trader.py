"""
execution/paper_trader.py — Exécution simulée (paper trading) via CCXT testnet.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime

logger = logging.getLogger("zeitgeist.paper_trader")


class PaperTrader:
    """Exécute des ordres simulés sur le testnet Binance via CCXT."""

    def __init__(self):
        from utils.config import load_settings, get_env
        cfg = load_settings()
        exchange_cfg = cfg.get("exchange", {})
        self.exchange_name: str = exchange_cfg.get("name", "binance")
        self.capital: float = exchange_cfg.get("paper_capital_usd", 10000.0)
        self.testnet: bool = exchange_cfg.get("testnet", True)
        # Offset Maker : on poste un ordre limite légèrement meilleur que le cours
        # BUY  → limit à prix * (1 - offset)  → on attend que le marché descende vers nous
        # SELL → limit à prix * (1 + offset)  → on attend que le marché monte vers nous
        self.limit_offset: float = exchange_cfg.get("limit_order_offset_pct", 0.10) / 100
        self.limit_timeout_s: int = int(exchange_cfg.get("limit_fill_timeout_s", 120))
        self._exchange = self._init_exchange(exchange_cfg)

    def _init_exchange(self, cfg: dict):
        """Initialise la connexion CCXT."""
        try:
            import ccxt
            from utils.config import get_env

            exchange_class = getattr(ccxt, self.exchange_name)
            exchange = exchange_class({
                "apiKey": get_env("BINANCE_API_KEY", required=False) or "paper",
                "secret": get_env("BINANCE_API_SECRET", required=False) or "paper",
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
            })

            if cfg.get("testnet", True):
                exchange.set_sandbox_mode(True)

            logger.info(f"Exchange {self.exchange_name} initialisé (testnet={cfg.get('testnet', True)})")
            return exchange
        except Exception as exc:
            logger.warning(f"CCXT non disponible ({exc}) — mode simulation pure")
            return None

    def execute(self, decision: dict) -> dict:
        """
        Exécute un ordre paper trade via ordre LIMITE (stratégie Maker).

        BUY  : limite à entry_price * (1 - offset) — on achète en-dessous du cours
        SELL : limite à entry_price * (1 + offset) — on vend au-dessus du cours

        En simulation pure : l'ordre est considéré rempli au prix limite
        (BTC a suffisamment de volatilité intraday pour atteindre +/-0.1% en 30min).
        Si le timeout est dépassé en mode CCXT réel, l'ordre est annulé (missé).
        """
        action = decision.get("action", "HOLD")
        size_usd = decision.get("position_size_usd", 0)
        entry_price = decision.get("entry_price", 0)

        if action == "HOLD" or size_usd <= 0:
            return {"status": "skipped", "reason": "HOLD or zero size"}

        # Prix limite Maker : légèrement SOUS le marché pour BUY, AU-DESSUS pour SELL
        if action == "BUY":
            limit_price = round(entry_price * (1 - self.limit_offset), 2)
        else:
            limit_price = round(entry_price * (1 + self.limit_offset), 2)

        # Tentative d'ordre limite réel via CCXT testnet
        order_id = None
        fill_price = limit_price
        status = "executed"

        # Actifs non-crypto (forex, commodités) → simulation pure sans CCXT
        from agents.market_data_agent import _YAHOO_SYMBOLS
        symbol = decision.get("symbol", "BTC/USDT")
        is_non_crypto = symbol in _YAHOO_SYMBOLS
        if is_non_crypto:
            logger.info(
                f"[{symbol}] Actif non-crypto — simulation pure (pas d'ordre CCXT). "
                f"Prix de référence Yahoo Finance @ {limit_price:.4f}"
            )

        if self._exchange and entry_price > 0 and not is_non_crypto:
            try:
                qty = round(size_usd / limit_price, 6)
                side = "buy" if action == "BUY" else "sell"

                order = self._exchange.create_limit_order(
                    symbol, side, qty, limit_price
                )
                order_id = order.get("id")
                logger.info(f"Ordre limite CCXT posté — id={order_id} {side} @ {limit_price:.2f}")

                # Attente de fill jusqu'au timeout
                deadline = time.time() + self.limit_timeout_s
                while time.time() < deadline:
                    time.sleep(5)
                    o = self._exchange.fetch_order(order_id, symbol)
                    if o["status"] == "closed":
                        fill_price = float(o.get("average", limit_price) or limit_price)
                        logger.info(f"Ordre limite rempli @ {fill_price:.2f}")
                        break
                    if o["status"] == "canceled":
                        status = "canceled"
                        break
                else:
                    # Timeout — annulation
                    try:
                        self._exchange.cancel_order(order_id, symbol)
                    except Exception:
                        pass
                    status = "timeout"
                    logger.warning(f"Ordre limite timeout après {self.limit_timeout_s}s — annulé")

            except Exception as exc:
                logger.warning(f"Ordre CCXT échoué (simulation pure): {exc}")

        if status not in ("executed",):
            return {"status": status, "reason": f"Limite non remplie ({status})"}

        result = {
            "status": "executed",
            "order_type": "limit",
            "order_id": order_id or f"SIM-LMT-{int(time.time())}",
            "action": action,
            "fill_price": round(fill_price, 2),
            "limit_price": limit_price,
            "market_price": entry_price,
            "price_improvement": round((entry_price - fill_price) * (1 if action == "BUY" else -1), 2),
            "size_usd": size_usd,
            "timestamp": datetime.utcnow().isoformat(),
            "sl_price": decision.get("sl_price", 0),
            "tp_price": decision.get("tp_price", 0),
        }

        logger.info(
            f"Trade Maker exécuté — {action} {size_usd:.0f}$ @ {fill_price:.2f} "
            f"(amélioration: {result['price_improvement']:+.2f}$ vs marché)"
        )
        return result

    def get_portfolio(self, asset: str | None = None) -> dict:
        """Retourne le portefeuille courant, par actif ou global.

        - asset=None  : portfolio consolidé tous actifs
        - asset="BTC/USDT" : portfolio isolé pour cet actif

        Mode LIVE (testnet=False) : lit le solde réel via CCXT fetch_balance().
        Mode PAPER (testnet=True) : calcule depuis l'historique SQLite.
        """
        # ── Résoudre le capital de référence ──────────────────────────────
        if asset:
            capital = self._get_asset_capital(asset)
        else:
            capital = self.capital

        # ── Mode LIVE : solde réel depuis l'exchange ──────────────────────
        if not self.testnet and self._exchange and not asset:
            # En mode live on lit le solde global (pas filtrable par actif)
            try:
                balance = self._exchange.fetch_balance()
                usdt_free  = float((balance.get("USDT") or {}).get("free",  0))
                usdt_total = float((balance.get("USDT") or {}).get("total", 0))
                btc_total  = float((balance.get("BTC")  or {}).get("total", 0))
                btc_price  = 0.0
                try:
                    ticker = self._exchange.fetch_ticker("BTC/USDT")
                    btc_price = float(ticker.get("last") or 0)
                except Exception:
                    pass
                current_value = usdt_total + btc_total * btc_price
                return {
                    "capital":       capital,
                    "current_value": round(current_value, 2),
                    "usdt_free":     round(usdt_free, 2),
                    "btc_total":     btc_total,
                    "total_pnl":     round(current_value - capital, 2),
                    "total_pnl_pct": round((current_value - capital) / capital * 100, 2)
                                     if capital else 0.0,
                    "live_mode":     True,
                    "asset":         "ALL",
                }
            except Exception as exc:
                logger.warning(f"fetch_balance échoué, fallback SQLite: {exc}")

        # ── Mode PAPER/TESTNET : calcul depuis l'historique SQLite ────────
        try:
            from storage.database import get_recent_decisions, get_pnl_history

            if asset:
                # P&L filtré sur l'actif
                from storage.database import get_recent_trades as _grt, count_trades as _ct
                trades = _grt(1000, asset=asset)
                total_pnl = sum(t.get("result_24h", 0) or 0 for t in trades)
                n_trades = _ct(asset=asset)
            else:
                pnl_rows = get_pnl_history()
                total_pnl = sum(p.get("result_24h", 0) or 0 for p in pnl_rows)
                from storage.database import count_trades as _ct
                n_trades = _ct()

            return {
                "capital":       capital,
                "current_value": round(capital + total_pnl, 2),
                "total_pnl":     round(total_pnl, 2),
                "total_pnl_pct": round(total_pnl / capital * 100, 2) if capital else 0.0,
                "n_trades":      n_trades,
                "asset":         asset or "ALL",
                "live_mode":     False,
            }
        except Exception:
            return {
                "capital": capital, "current_value": capital,
                "total_pnl": 0, "total_pnl_pct": 0, "n_trades": 0,
                "asset": asset or "ALL", "live_mode": False,
            }

    def _get_asset_capital(self, asset: str) -> float:
        """Lit paper_capital_usd depuis config/assets/{slug}.yaml, fallback settings."""
        try:
            from utils.config import load_asset_config
            cfg = load_asset_config(asset)
            cap = cfg.get("paper_capital_usd")
            if cap:
                return float(cap)
        except Exception:
            pass
        return self.capital
