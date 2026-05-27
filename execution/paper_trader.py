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
        _YAHOO_SYMBOLS: dict[str, str] = {
            "XAU/USD": "GC=F",
            "XAG/USD": "SI=F",
            "WTI/USD": "CL=F",
            "EUR/USD": "EURUSD=X",
            "GBP/USD": "GBPUSD=X",
            "USD/JPY": "JPY=X",
            "AUD/USD": "AUDUSD=X",
        }
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
            from storage.database import (
                get_pnl_history,
                count_trades as _ct,
                get_v2_assets_summary,
                get_v2_equity_curve,
                get_v2_realized_stats,
                get_connection,
            )

            if asset:
                # P&L filtré sur l'actif
                n_trades = _ct(asset=asset)
                # Priorité V2: equity live (cohérent avec les décisions long/short V2)
                v2_curve = get_v2_equity_curve(n=1, asset=asset)
                if v2_curve:
                    current_value = float(v2_curve[-1].get("equity") or capital)
                    # Base de référence = première equity V2 de l'actif (pas le config asset)
                    # -> évite les incohérences si paper_capital_usd diffère du moteur V2.
                    try:
                        with get_connection() as conn:
                            _r0 = conn.execute(
                                "SELECT equity FROM v2_equity WHERE asset = ? ORDER BY ts ASC LIMIT 1",
                                (asset,),
                            ).fetchone()
                        if _r0 and _r0["equity"] is not None:
                            capital = float(_r0["equity"])
                    except Exception:
                        pass
                    _st = get_v2_realized_stats(asset=asset)
                    total_pnl = float(_st.get("total_pnl", current_value - capital) or 0.0)
                    n_trades = int(_st.get("n_trades", n_trades) or 0)
                else:
                    # Fallback V1: somme des résultats post-mortem (result_24h)
                    pnl_rows = get_pnl_history()
                    total_pnl = sum((r.get("result_24h", 0) or 0) for r in pnl_rows if r.get("asset") == asset)
                    current_value = capital + total_pnl
            else:
                n_trades = _ct()
                # Priorité V2 multi-actifs: somme des dernières equity par actif
                v2_assets = get_v2_assets_summary()
                if v2_assets:
                    # Filtrer aux actifs réellement actifs dans la config daemon.
                    try:
                        from utils.config import load_settings as _ls
                        _active_assets = set((_ls().get("project", {}) or {}).get("active_assets", []) or [])
                    except Exception:
                        _active_assets = set()

                    # Dédupliquer robustement par actif (sécurité si source duplique une ligne).
                    _by_asset: dict[str, dict] = {}
                    for row in v2_assets:
                        _asset = str(row.get("asset") or "")
                        if not _asset:
                            continue
                        if _active_assets and _asset not in _active_assets:
                            continue
                        _by_asset[_asset] = row

                    _rows = list(_by_asset.values())
                    _assets = [str(r.get("asset") or "") for r in _rows if str(r.get("asset") or "")]
                    base_capital = 0.0
                    current_value = 0.0
                    for row in _rows:
                        _a = str(row.get("asset") or "")
                        _cur_eq = float(row.get("equity") or 0.0)
                        current_value += _cur_eq
                        # Base de référence = première equity V2 par actif.
                        try:
                            with get_connection() as conn:
                                _r0 = conn.execute(
                                    "SELECT equity FROM v2_equity WHERE asset = ? ORDER BY ts ASC LIMIT 1",
                                    (_a,),
                                ).fetchone()
                            _base_eq = float(_r0["equity"]) if (_r0 and _r0["equity"] is not None) else self.capital
                        except Exception:
                            _base_eq = self.capital
                        base_capital += _base_eq
                    capital = base_capital if base_capital > 0 else capital
                    _st = get_v2_realized_stats(assets=_assets)
                    total_pnl = float(_st.get("total_pnl", current_value - capital) or 0.0)
                    n_trades = int(_st.get("n_trades", n_trades) or 0)
                else:
                    # Fallback V1
                    pnl_rows = get_pnl_history()
                    total_pnl = sum(p.get("result_24h", 0) or 0 for p in pnl_rows)
                    current_value = capital + total_pnl

            return {
                "capital":       capital,
                "current_value": round(current_value, 2),
                "total_pnl":     round(total_pnl, 2),
                "total_pnl_pct": round(total_pnl / capital * 100, 2) if capital else 0.0,
                "n_trades":      n_trades,
                "asset":         asset or "ALL",
                "live_mode":     False,
            }
        except Exception:
            logger.exception("get_portfolio fallback to zeros")
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
