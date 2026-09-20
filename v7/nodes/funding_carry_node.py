"""
v7/nodes/funding_carry_node.py — Nœud Funding Carry V7.

Fetch le funding rate, évalue le hurdle économique, produit un signal.
Appelé par v7/run_carry_cycle.py (cycle carry unique, 8h).

Output: signal carry (open/close/flat) + expected_return + size
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import numpy as np

from v4.core.node import NodeRunResult, NodeStatus

logger = logging.getLogger("funding_carry_node")


@dataclass
class FundingCarryState:
    """État persistant du nœud Funding Carry."""
    symbol: str
    position_open: bool = False
    entry_capital: float = 0.0
    entry_spot: float = 0.0          # spot price at entry
    entry_perp: float = 0.0          # perp price at entry
    entry_time: str = ""             # ISO timestamp d'ouverture (time-stop)
    negative_since: Optional[str] = None  # ISO timestamp
    total_funding_received: float = 0.0
    n_payments: int = 0
    staking_earned: float = 0.0      # USDT staking yield on idle capital
    last_funding_rate: float = 0.0
    last_signal: str = "flat"
    last_update: str = ""


class FundingCarryNode:
    """Nœud DAG pour le funding carry.
    
    Compatible avec le framework DAG Atlas.
    Implémente l'interface minimale: run(inputs), execute(inputs), output_schema().
    
    Usage dans un DAG:
        node = FundingCarryNode(node_id="btc_carry", symbol="BTC/USDT", capital=5000)
        outputs = node.run({"spot_price": 67000})
    """

    def __init__(
        self,
        node_id: str = "funding_carry",
        symbol: str = "BTC/USDT",
        capital: float = 10_000,
        fraction: float = 0.50,
        min_funding: float = 0.00005,
        max_funding: float = 0.003,
        exit_after_hours: int = 72,    # exit on negative funding after 72h (Grok)
        kelly_fraction: float = 0.35,  # fractional Kelly 35% (Grok)
        max_hold_days: int = 14,        # time-stop: forced exit after N days
        stop_loss_pct: float = -0.05,   # stop-loss basis : -5%
        cooldown_hours: int = 24,       # anti-churn: do not reopen within N hours of closing
        exchange_name: str = "binance",  # binance | bybit | okx | kraken
        fee_bps: float = 10.0,       # frais spot Binance standard (0.1% = 10bps)
        slippage_bps: float = 2.0,
        params: dict | None = None,
        meta: object = None,  # DAG framework NodeMeta
    ):
        # If called through the DAG framework (params dict), extract the values
        if params is not None:
            symbol = params.get("symbol", symbol)
            capital = params.get("capital", capital)
            fraction = params.get("fraction", fraction)
            min_funding = params.get("min_funding", min_funding)
            max_funding = params.get("max_funding", max_funding)
            exit_after_hours = params.get("exit_after_hours", exit_after_hours)
            max_hold_days = params.get("max_hold_days", max_hold_days)
            stop_loss_pct = params.get("stop_loss_pct", stop_loss_pct)
            exchange_name = params.get("exchange", exchange_name)
        
        self.node_id = node_id
        self.params = params or {}       # DAG framework
        self.meta = meta                 # DAG framework
        self.symbol = symbol
        self.capital = capital
        self.fraction = fraction
        self.min_funding = min_funding
        self.max_funding = max_funding
        self.exit_after_hours = exit_after_hours
        self.kelly_fraction = kelly_fraction
        self.max_hold_days = max_hold_days
        self.stop_loss_pct = stop_loss_pct
        self.cooldown_hours = int(params.get("cooldown_hours", cooldown_hours)) if params else cooldown_hours
        self.exchange_name = exchange_name
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        
        # Regime filter: 30d volatility is the minimum to enter (via DAG params or default)
        self.min_volatility_30d = float(self.params.get("min_volatility_30d", 0.02))
        
        # Hurdle economique (configurable via grid search)
        # Default 5% = SOFR seul (grid search: 25/26 actifs preferent 5%)
        self.economic_hurdle = float(self.params.get("economic_hurdle", 0.05))
        
        self.state = FundingCarryState(symbol=symbol)
        self._funding_rate_history: list[float] = []  # 7d moving average (~21 samples)
        
        # Restore state from the DB (survives restarts)
        # Sauf en mode backtest (pas de DB live)
        backtest = params.get("_backtest", False) if params else False
        if not backtest:
            self._restore_state()
    
    def _restore_state(self):
        """Vérifie si une position carry est déjà ouverte pour ce symbole.
        
        Restaure TOUS les champs nécessaires au suivi de position :
        entry_spot, entry_perp, entry_time, entry_capital,
        total_funding_received, n_payments.
        Sans ces valeurs, les vérifications SL/TP/time-stop sont ignorées.
        """
        try:
            from storage.paper_trader import get_open_positions
            import json as _json
            open_pos = get_open_positions(symbol=self.symbol)
            carry_pos = [p for p in open_pos if p.get("action") in ("carry", "short")]
            if carry_pos:
                pos = carry_pos[0]
                self.state.position_open = True
                self.state.entry_capital = float(pos.get("size_usd", 0))
                # Restore the spot entry price (stored in entry_price)
                self.state.entry_spot = float(pos.get("entry_price", 0) or 0)
                # Restore the perp price from context_json when available
                ctx_raw = pos.get("context_json")
                if ctx_raw:
                    try:
                        ctx = _json.loads(ctx_raw) if isinstance(ctx_raw, str) else ctx_raw
                        # Restore accumulated funding (persisted by run_carry_cycle.py on HOLD)
                        self.state.total_funding_received = float(ctx.get("total_funding_received", 0) or 0)
                        self.state.n_payments = int(ctx.get("n_payments", 0) or 0)
                        # context_json holds the full decision dict
                        # entry_price = spot, on cherche le perp dans carry_* ou on l'estime
                        if ctx.get("carry_signal") == "open_carry":
                            # The perp was close to spot at entry (basis ~0)
                            self.state.entry_perp = self.state.entry_spot
                    except Exception:
                        self.state.entry_perp = self.state.entry_spot
                else:
                    # No context: estimate perp ~ spot (the basis is usually small)
                    self.state.entry_perp = self.state.entry_spot
                # Restore the entry timestamp (for the time-stop)
                ts = pos.get("timestamp", "")
                if ts:
                    self.state.entry_time = ts
                logger.info(
                    "[%s] Position carry restaurée : spot=%.2f perp=%.2f capital=$%.0f opened=%s",
                    self.node_id, self.state.entry_spot, self.state.entry_perp,
                    self.state.entry_capital, self.state.entry_time[:19] if self.state.entry_time else "?"
                )
        except Exception as e:
            logger.debug("[%s] DB restore skipped: %s", self.node_id, e)

    def _get_funding_interval(self) -> float:
        """Retourne l'intervalle de funding en heures depuis Binance (3 audits, 20/07/2026).
        Fallback: 8h si l'API est injoignable ou si backtest."""
        # Backtest: no CCXT call, use the standard 8h
        if self.params.get("_backtest", False):
            return 8.0
        # Simple cache (the interval does not change at runtime)
        if hasattr(self, "_cached_funding_interval"):
            return self._cached_funding_interval
        try:
            import ccxt
            exchange = ccxt.binance({"enableRateLimit": True})
            # Use fetch_funding_rate(), which is lighter than load_markets()
            market = exchange.market(self.symbol)
            info = market.get("info", {}) if market else {}
            interval = float(info.get("fundingIntervalHours", 8) or 8)
            self._cached_funding_interval = max(4, min(interval, 24))
            return self._cached_funding_interval
        except Exception:
            return 8.0  # fallback standard

    def _funding_in_top_percentile(self, funding_rate: float, pct: float = 0.20,
                                    window_days: int = 90) -> bool:
        """Vérifie si le funding_rate actuel est dans le top pct% de l'historique récent.
        Utilise l'historique local (max 21 valeurs = 7 jours).
        Pour window_days > 7, on utilise ce qu'on a + hypothèse conservative.
        (3 audits, 20/07/2026)"""
        if not self._funding_rate_history or len(self._funding_rate_history) < 5:
            return True  # pas assez d'historique → laisse passer
        # Use the available history (up to 21 samples = 7 days)
        sorted_rates = sorted(self._funding_rate_history)
        threshold_idx = int(len(sorted_rates) * (1 - pct))
        if threshold_idx >= len(sorted_rates):
            threshold_idx = len(sorted_rates) - 1
        threshold = sorted_rates[threshold_idx]
        return funding_rate >= threshold

    # ── DAG framework compatibility ──
    
    @staticmethod
    def output_schema() -> dict[str, str]:
        return {
            "signal": "str", "size_usd": "float", "expected_return": "float",
            "confidence": "float", "reason": "str", "funding_rate": "float",
            "annual_funding_pct": "float", "position_open": "bool",
            "total_funding_received": "float", "n_payments": "int",
            "decision": "dict",  # format PaperTrader: {action, size_usd, entry_price, ...}
        }
    
    @staticmethod
    def input_schema() -> dict[str, str]:
        return {"symbol": "str", "spot_price": "float", "funding_rate": "float", "perp_price": "float"}
    
    def execute(self, inputs: dict[str, Any]) -> NodeRunResult:
        """Point d'entrée DAG framework → délègue à run()."""
        import time as _time
        t0 = _time.time()
        try:
            outputs = self.run(inputs)
            return NodeRunResult(
                node_id=self.node_id,
                status=NodeStatus.DONE,
                outputs=outputs,
                duration_ms=(_time.time() - t0) * 1000,
            )
        except Exception as e:
            return NodeRunResult(
                node_id=self.node_id,
                status=NodeStatus.ERROR,
                error=str(e),
                duration_ms=(_time.time() - t0) * 1000,
            )
    
    # ── Data fetching ──
    
    def _get_exchange(self):
        """Retourne l'instance CCXT configurée (binance | bybit | okx | kraken)."""
        import ccxt
        ex_map = {
            "binance": ccxt.binance, "bybit": ccxt.bybit,
            "okx": ccxt.okx, "kraken": ccxt.kraken,
        }
        return ex_map.get(self.exchange_name, ccxt.binance)({"enableRateLimit": True})

    @staticmethod
    def _perp_symbol(symbol: str) -> str:
        """Convertit un symbole spot en symbole perp USDⓈ-M (gère les contrats ×1000)."""
        base = symbol.split("/")[0]
        MULTIPLIER_MAP = {"PEPE": "1000PEPE", "SHIB": "1000SHIB", "BONK": "1000BONK",
                          "FLOKI": "1000FLOKI", "LUNC": "1000LUNC"}
        base_perp = MULTIPLIER_MAP.get(base, base)
        return f"{base_perp}/USDT:USDT"

    @staticmethod
    def _perp_multiplier(symbol: str) -> float:
        """Multiplicateur du contrat perp USDⓈ-M : 1000 pour les contrats ×1000
        (le prix du contrat vaut ×1000 le prix spot du token), 1 sinon.
        Indispensable pour que la basis (perp − spot)/spot soit correcte."""
        base = symbol.split("/")[0]
        return 1000.0 if base in {"PEPE", "SHIB", "BONK", "FLOKI", "LUNC"} else 1.0

    @staticmethod
    def _staking_annual_rate() -> float:
        """Taux de staking annuel du capital inactif (carry_assets.yaml, clé
        global.staking_annual). Lu depuis la config pour que la valeur affichée
        dans l'admin ait réellement un effet."""
        try:
            from v7.core.asset_config import get_global_params
            return float(get_global_params().get("staking_annual", 0.05))
        except Exception:
            return 0.05

    def fetch_current_funding(self) -> float:
        """Fetch le funding rate actuel."""
        try:
            import ccxt
            exchange = self._get_exchange()
            symbol_perp = self._perp_symbol(self.symbol)
            rates = exchange.fetch_funding_rates([symbol_perp])
            if rates and symbol_perp in rates:
                return float(rates[symbol_perp]["fundingRate"])
        except Exception as e:
            logger.warning("Funding fetch failed for %s: %s", self.symbol, e)
        
        # Fallback: Binance public API
        try:
            import requests
            symbol_clean = self._perp_symbol(self.symbol).replace("/", "").replace(":USDT", "")
            resp = requests.get(
                "https://fapi.binance.com/fapi/v1/premiumIndex",
                params={"symbol": symbol_clean},
                timeout=10,
            )
            data = resp.json()
            return float(data.get("lastFundingRate", 0))
        except Exception:
            return 0.0
    
    def fetch_spot_price(self) -> float:
        """Fetch le prix spot actuel avec retry + log en cas d'échec."""
        import time as _time
        last_err = ""
        for attempt in range(3):
            try:
                exchange = self._get_exchange()
                ticker = exchange.fetch_ticker(self.symbol)
                price = float(ticker.get("last", 0))
                if price > 0:
                    return price
                last_err = f"price=0 from ticker"
            except Exception as e:
                last_err = str(e)[:120]
            if attempt < 2:
                _time.sleep(1.0 * (attempt + 1))  # backoff: 1s, 2s
        logger.warning("[%s] fetch_spot_price FAILED after 3 attempts: %s", self.node_id, last_err)
        return 0.0
    
    def fetch_perp_price(self) -> float:
        """Fetch le prix du perpetual (normalisé au prix par token) avec retry."""
        import time as _time
        last_err = ""
        for attempt in range(3):
            try:
                exchange = self._get_exchange()
                symbol_perp = self._perp_symbol(self.symbol)
                ticker = exchange.fetch_ticker(symbol_perp)
                price = float(ticker.get("last", 0))
                if price > 0:
                    return price / self._perp_multiplier(self.symbol)
                last_err = f"price=0 from ticker"
            except Exception as e:
                last_err = str(e)[:120]
            if attempt < 2:
                _time.sleep(1.0 * (attempt + 1))
        logger.warning("[%s] fetch_perp_price FAILED after 3 attempts: %s", self.node_id, last_err)
        return 0.0

    def _last_close_age_hours(self) -> float | None:
        """Heures depuis la dernière clôture de ce symbole (None si jamais fermé).

        Anti-churn : empêche de rouvrir un actif dont le funding vient de
        basculer (ex: SHIB/PEPE) et qui coûterait des frais de round-trip
        à répétition.
        """
        try:
            from storage.database import get_connection
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT closed_at FROM v4_trades "
                    "WHERE symbol=? AND status='closed' "
                    "ORDER BY closed_at DESC LIMIT 1",
                    (self.symbol,),
                ).fetchone()
            if not row or not row[0]:
                return None
            closed_at = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - closed_at).total_seconds() / 3600
        except Exception:
            return None
    
    # ── Decision logic ──

    
    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Exécute le nœud Funding Carry.
        
        Args:
            inputs: dict avec:
                - spot_price (float): prix spot actuel
                - funding_rate (float, optional): override le fetch auto
                - perp_price (float, optional): prix du perpetual
        
        Returns:
            dict avec signal, size_usd, expected_return, confidence, reason
        """
        t0 = time.time()
        
        # The node is bound to ONE asset: self.symbol is authoritative.
        # L'etat interne (position ouverte, capital engage, historique de funding)
        # state is not reset between calls - so callers instantiate
        # one node per asset (run_carry_cycle, backtests).
        
        spot_price = float(inputs.get("spot_price", 0))
        funding_rate = float(inputs.get("funding_rate", 0))
        perp_price = float(inputs.get("perp_price", spot_price))
        
        # Fetch spot/perp price si pas fourni (sauf backtest)
        if spot_price == 0 and not self.params.get("_backtest", False):
            spot_price = self.fetch_spot_price()
        
        if perp_price == 0 and not self.params.get("_backtest", False):
            perp_price = self.fetch_perp_price()
        if perp_price == 0:
            perp_price = spot_price
        
        # Fetch funding rate si pas fourni (sauf backtest: on garde 0)
        if funding_rate == 0 and not self.params.get("_backtest", False):
            funding_rate = self.fetch_current_funding()
        
        self.state.last_funding_rate = funding_rate
        self.state.last_update = datetime.now().isoformat()
        
        # Keep the funding history for the 7d MA and the percentile (max 270 samples = 90d)
        self._funding_rate_history.append(funding_rate)
        if len(self._funding_rate_history) > 270:
            self._funding_rate_history = self._funding_rate_history[-270:]
        funding_ma_7d = sum(self._funding_rate_history[-21:]) / min(len(self._funding_rate_history), 21) if self._funding_rate_history else funding_rate
        
        # ── Decision ──
        signal = "flat"
        size_usd = 0.0
        expected_return = 0.0
        confidence = 0.5
        reason = ""
        unrealized_pct = 0.0
        economic_hurdle = self.economic_hurdle  # scoped for both open/close branches
        
        # Annualise - uses Binance's real interval (3 audits, 2026-07-20)
        funding_interval_h = self._get_funding_interval()
        periods_per_year = (24 / funding_interval_h) * 365
        annual_funding = funding_rate * periods_per_year
        
        # Basis: entry-quality filter only.
        # The basis is NOT annualised into the expected return (there is no convergence
        # guarantee, and a negative basis must not cancel the funding yield).
        # Voir plus bas : expected_return = annual_funding seul.
        if perp_price > 0:
            basis_pct = (perp_price - spot_price) / spot_price
        else:
            basis_pct = 0.0
        
        if not self.state.position_open:
            # -- Staking on idle capital --
            staking_annual = self._staking_annual_rate()  # carry_assets.yaml (global)
            idle_capital = self.capital * self.fraction
            staking_8h = idle_capital * staking_annual / (365 * 3)  # 3 funding periods of 8h per day
            self.state.staking_earned += staking_8h
            
            # -- Entry opportunity --
            # Anti-churn cooldown: do not reopen a recently closed asset
            _close_age_h = self._last_close_age_hours()
            if _close_age_h is not None and _close_age_h < self.cooldown_hours:
                reason = f"cooldown {self.cooldown_hours}h après clôture ({_close_age_h:.1f}h)"
                confidence = 0.1
            # Filter 1: instantaneous funding within range
            elif funding_rate >= self.min_funding and funding_rate <= self.max_funding:
                # Filter 2: positive 7d funding MA (avoids isolated spikes)
                if funding_ma_7d <= 0:
                    reason = f"funding MA 7j={funding_ma_7d*100:.4f}% ≤ 0 → attente"
                    confidence = 0.2
                # Filter 3: basis not too unfavourable
                elif basis_pct < -0.003:
                    reason = f"basis défavorable ({basis_pct*100:.4f}%)"
                    confidence = 0.3
                else:
                    # ── Rendement attendu (22/07/2026) ──
                    # Funding is annualised; the basis is an entry-quality filter only.
                    # The basis is NOT annualised into the return - there is no convergence
                    # guarantee, and a negative basis must not cancel the funding
                    # yield (GPT round 2: expected_basis_return = 0).
                    expected_return = annual_funding  # funding return only
                    
                    # -- Economic hurdle = SOFR (pure opportunity cost) --
                    # The risk premia (exchange, stablecoin, operational) are covered
                    # by safety_cap and stress_loss_pct, not by the hurdle.
                    # Grid search V7.3: 25/26 actifs preferent 5% vs 7%.
                    
                    # -- Annualised costs (deducted from the return, not from the hurdle) --
                    round_trip_cost = 0.0048   # 48bps (40 fees + 8 slippage)
                    # The annualised cost depends on the real time-stop: a short hold
                    # makes the fees prohibitive (48bps amortised over very few days).
                    # Ex: max_hold_days=14 → 12.5%/an de frais ; 60j → 2.9%/an.
                    estimated_hold = max(self.max_hold_days, 1)
                    annualized_cost = round_trip_cost * 365 / estimated_hold
                    net_expected_return = expected_return - annualized_cost
                    
                    # -- Percentile filter (relative, separate from the economic hurdle) --
                    percentile_ok = True
                    if len(self._funding_rate_history) >= 30:
                        annualized_hist = sorted([r * periods_per_year for r in self._funding_rate_history])
                        p60 = annualized_hist[int(len(annualized_hist) * 0.60)]
                        percentile_ok = annual_funding >= p60
                    
                    if net_expected_return > economic_hurdle and percentile_ok:
                            # ── Risk budgeting (GPT 5.5 + 3 audits) ──
                            # -- Risk budgeting - per-asset stress loss (from config or fallback) --
                            try:
                                from v7.core.asset_config import get_asset_params
                                _cfg = get_asset_params(self.symbol)
                                stress_loss_pct = float(_cfg.get("stress_loss_pct", 0.10))
                            except Exception:
                                _per_asset_stress = {
                                    "BTC": 0.04, "ETH": 0.04,
                                    "SOL": 0.08, "BNB": 0.08,
                                    "XRP": 0.12, "ADA": 0.12, "DOGE": 0.12,
                                    "AVAX": 0.10, "LINK": 0.10, "DOT": 0.10,
                                    "LTC": 0.06, "NEAR": 0.12, "SUI": 0.12,
                                }
                                stress_loss_pct = _per_asset_stress.get(
                                    self.symbol.split("/")[0].upper(), 0.10)
                            net_return = net_expected_return - economic_hurdle
                            score = max(0, net_return) / stress_loss_pct if stress_loss_pct > 0 else 0
                            raw_size = self.capital * self.fraction * min(score, 0.25)

                            # -- Safety caps (from config or fallback) --
                            try:
                                _cfg = get_asset_params(self.symbol)
                                max_size = float(_cfg.get("safety_cap", 200))
                            except Exception:
                                safety_caps = {
                                    "BTC": 400, "ETH": 300, "SOL": 200, "BNB": 200,
                                    "XRP": 200, "ADA": 150, "DOGE": 100,
                                    "AVAX": 150, "LINK": 150, "DOT": 150,
                                    "LTC": 200, "NEAR": 100, "SUI": 100,
                                }
                                coin = self.symbol.split("/")[0].upper()
                                max_size = safety_caps.get(coin, 200)
                            min_size = 50

                            size_usd = min(raw_size, max_size)
                            if size_usd < min_size:
                                reason = f"taille ${size_usd:.0f} < min ${min_size} → skip"
                                confidence = 0.3
                            else:
                                # ── Global Allocator check (3 audits consensus, 20/07/2026) ──
                                from v7.core.global_allocator import can_open_position
                                alloc_ok, alloc_reason = can_open_position(
                                    self.symbol, size_usd, score)
                                if not alloc_ok:
                                    reason = f"GlobalAllocator: {alloc_reason}"
                                    confidence = 0.3
                                else:
                                    # ── DB safety check (anti-duplicate, 24/07/2026) ──
                                    from storage.paper_trader import get_open_positions
                                    _db_open = get_open_positions(symbol=self.symbol)
                                    _db_carry = [p for p in _db_open if p.get("action") in ("carry", "short")]
                                    if _db_carry:
                                        # Sync in-memory state with DB reality
                                        self.state.position_open = True
                                        reason = f"DB safety: position déjà ouverte (id={_db_carry[0].get('trade_id','?')})"
                                        confidence = 0.1
                                        logger.warning("[%s] %s", self.node_id, reason)
                                    else:
                                        self.state.position_open = True
                                        self.state.entry_capital = size_usd
                                        self.state.entry_spot = spot_price
                                        self.state.entry_perp = perp_price if perp_price > 0 else spot_price
                                        self.state.entry_time = datetime.now().isoformat()
                                        self.state.negative_since = None
                                        signal = "open_carry"
                                        confidence = min(0.90, 0.50 + score * 2)
                                        reason = (f"funding={funding_rate*100:.4f}% MA={funding_ma_7d*100:.4f}% "
                                                  f"→ net={net_expected_return*100:.1f}%/an (hurdle={economic_hurdle*100:.0f}%) | "
                                                  f"size=${size_usd:.0f} (score={score:.2f}, cap=${max_size})")
                    else:
                        reason = f"retour net {net_expected_return*100:.1f}%/an < {economic_hurdle*100:.0f}% hurdle"
                        confidence = 0.5
            else:
                reason = f"funding={funding_rate*100:.4f}% hors [min={self.min_funding*100:.4f}%, max={self.max_funding*100:.2f}%]"
        else:
            # ── Position ouverte ──
            # Compute unrealised P&L (basis only; the delta is hedged)
            if self.state.entry_spot > 0 and spot_price > 0:
                # Short perp: on perd si perp monte vs spot, on gagne si perp baisse vs spot
                basis_entry = (self.state.entry_perp - self.state.entry_spot) / self.state.entry_spot
                basis_now = (perp_price - spot_price) / spot_price if perp_price > 0 else 0
                # LONG spot + SHORT perp → gain when basis CONTRACTS (Round 4 fix)
                unrealized_pct = basis_entry - basis_now  # positive = gain, negative = loss
                unrealized_usd = unrealized_pct * self.state.entry_capital
                
                # Stop-loss : basis loss > 5% → close
                if unrealized_pct < self.stop_loss_pct:
                    signal = "close_carry"
                    self.state.position_open = False
                    reason = f"STOP-LOSS: basis loss {unrealized_pct*100:.1f}% > {abs(self.stop_loss_pct)*100:.0f}% → close"
                    confidence = 0.95
                    logger.warning("[%s] %s", self.node_id, reason)
                
                # -- Economic exit (3 audits, 2026-07-20) --
                # Replaces the strict 14d time-stop.
                # ZONES : HEALTHY (<14j), REVIEW (14-30j), DERISK (30-60j), CLOSE (>60j)
                if signal != "close_carry" and self.state.entry_time:
                    try:
                        entry_dt = datetime.fromisoformat(self.state.entry_time)
                        days_held = (datetime.now() - entry_dt).total_seconds() / 86400
                        
                        if days_held > 60:
                            signal = "close_carry"
                            self.state.position_open = False
                            reason = f"ECONOMIC STOP (ZONE CLOSE): {days_held:.0f}j > 60j max"
                            confidence = 0.85
                            logger.warning("[%s] %s", self.node_id, reason)
                        elif days_held > 30:
                            # DERISK: close when forward funding no longer justifies the position
                            forward_funding = funding_rate * periods_per_year
                            exit_cost_annual = 0.0048 * (365 / max(days_held, 1))  # 48bps round-trip amortis
                            if forward_funding < economic_hurdle + exit_cost_annual:
                                signal = "close_carry"
                                self.state.position_open = False
                                reason = (f"ECONOMIC STOP (ZONE DERISK): {days_held:.0f}j, "
                                          f"forward funding={forward_funding*100:.1f}%/an < "
                                          f"hurdle+exit={(economic_hurdle+exit_cost_annual)*100:.1f}%/an")
                                confidence = 0.75
                                logger.warning("[%s] %s", self.node_id, reason)
                            else:
                                logger.info("[%s] DERISK zone: %dj, forward funding=%.1f%% > costs → hold",
                                           self.node_id, days_held, forward_funding*100)
                        elif days_held > 14:
                            logger.info("[%s] REVIEW zone: %dj — monitoring", self.node_id, days_held)
                    except Exception:
                        pass
            else:
                unrealized_pct = 0.0
            
            # ── Cross-margin risk monitoring ──
            # En paper trading, on simule le risque de liquidation du short perp
            # Si la perte latente > 80% du capital → alerte liquidation
            if unrealized_pct < -0.80 and self.state.position_open:
                logger.error("[%s] ⚠️ LIQUIDATION RISK: loss=%.1f%% → short perp would be liquidated!",
                           self.node_id, unrealized_pct * 100)
                # En paper, on ne ferme pas automatiquement mais on alerte fortement
            
            if signal == "close_carry":
                pass  # already handled above
            elif funding_rate > 0:
                # Recevoir funding
                payment = self.state.entry_capital * funding_rate
                self.state.total_funding_received += payment
                self.state.n_payments += 1
                signal = "flat"
                reason = f"carry actif | funding reçu={self.state.total_funding_received:.4f} ({self.state.n_payments} paiements)"
                confidence = 0.70
            elif funding_rate < 0:
                # Negative funding -> timer
                now = datetime.now()
                if self.state.negative_since is None:
                    self.state.negative_since = now.isoformat()
                
                try:
                    neg_start = datetime.fromisoformat(self.state.negative_since)
                    hours_neg = (now - neg_start).total_seconds() / 3600
                except Exception:
                    hours_neg = 0
                
                if hours_neg > self.exit_after_hours:
                    # Fermer
                    signal = "close_carry"
                    self.state.position_open = False
                    reason = f"funding négatif > {self.exit_after_hours}h → close"
                    confidence = 0.85
                else:
                    signal = "flat"
                    reason = f"funding négatif depuis {hours_neg:.0f}h (max {self.exit_after_hours}h)"
                    confidence = 0.50
            else:
                self.state.negative_since = None
        
        elapsed = time.time() - t0
        
        # ── Output ──
        # Construire un "decision" compatible PaperTrader.
        # For carry trades: NO spot SL/TP (semantically wrong for a delta-neutral book).
        # PositionMonitor uses the unified max_loss_pct (-5%) for the exit.
        # The DAG handles the basis stop-loss and the time-stop.
        # Score rounded to 0-100 for the dashboard display
        _display_score = round(min(score, 0.25) / 0.25 * 100) if signal == "open_carry" else 0
        decision = {
            "action": "flat",
            "size_usd": round(size_usd, 2),
            "entry_price": spot_price,
            "stop_loss": 0,       # no spot stop-loss on carry
            "take_profit": 0,     # no spot take-profit on carry
            "atr": 0,
            "strategy_type": "funding_carry",  # marker for downstream consumers
            "carry_signal": signal,
            "carry_expected_return": round(expected_return, 4),
            "carry_annual_pct": round(annual_funding * 100, 2),
            "score": _display_score,  # for the dashboard display
        }
        if signal == "open_carry":
            decision["action"] = "carry"
            # Two-leg accounting: store the entry prices to compute the basis P&L
            decision["entry_perp_price"] = perp_price if perp_price > 0 else spot_price
            decision["entry_basis"] = round(basis_pct, 6)
        elif signal == "close_carry":
            decision["action"] = "close_carry"
        
        outputs = {
            "signal": signal,
            "size_usd": round(size_usd, 2),
            "expected_return": round(expected_return, 4),
            "confidence": round(confidence, 2),
            "reason": reason,
            "funding_rate": funding_rate,
            "annual_funding_pct": round(annual_funding * 100, 2),
            "position_open": self.state.position_open,
            "total_funding_received": round(self.state.total_funding_received, 4),
            "n_payments": self.state.n_payments,
            "staking_earned": round(self.state.staking_earned, 4),
            "basis_pct": round(basis_pct * 100, 4),
            "entry_perp_price": perp_price if perp_price > 0 else spot_price,
            "entry_basis": round(basis_pct, 6),
            "unrealized_pnl_pct": round(unrealized_pct * 100, 2) if self.state.position_open else 0,
            "elapsed_s": round(elapsed, 3),
            "decision": decision,
        }
        
        logger.debug("[%s] signal=%s funding=%.6f size=$%.0f reason=%s",
                     self.node_id, signal, funding_rate, size_usd, reason)
        
        return outputs
    
    def reset(self):
        """Réinitialise l'état (pour backtest)."""
        self.state = FundingCarryState(symbol=self.symbol)
        self._funding_cache = []


# ── Test ──
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    
    node = FundingCarryNode(symbol="BTC/USDT", capital=10_000)
    
    # Simuler un signal d'ouverture
    result = node.run({
        "spot_price": 67000,
        "funding_rate": 0.0001,  # 0.01%
        "perp_price": 67005,
    })
    print(f"Signal: {result['signal']} | Size: ${result['size_usd']:.0f} | "
          f"Expected: {result['expected_return']*100:.1f}%/an | {result['reason']}")
    
    # Simuler paiement de funding
    result2 = node.run({
        "spot_price": 67100,
        "funding_rate": 0.0001,
    })
    print(f"Signal: {result2['signal']} | Funding reçu: {result2['total_funding_received']:.6f}")
    
    # Simulate negative funding
    node.state.negative_since = (datetime.now() - timedelta(hours=50)).isoformat()
    result3 = node.run({
        "spot_price": 66800,
        "funding_rate": -0.00005,
    })
    print(f"Signal: {result3['signal']} | {result3['reason']}")
