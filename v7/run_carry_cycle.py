"""
v7/run_carry_cycle.py — Single Funding Carry cycle script (replaces 29 DAGs).

DeepSeek/GPT audit (25/07/2026): the DAG infrastructure was oversized for the job.
This single script iterates over every configured asset, runs the FundingCarryNode
and records the decisions in the PaperTrader.

Usage:
    python v7/run_carry_cycle.py              # one cycle (manual)
    python v7/run_carry_cycle.py --daemon     # infinite loop every 8h (cron-like)

Recommended scheduling:
    # crontab -e
    0 */8 * * * cd /app/src && python v7/run_carry_cycle.py >> /app/data/carry_cycle.log 2>&1

Or inside Docker:
    docker exec atlas-v4-api python -B /app/src/v7/run_carry_cycle.py
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("carry_cycle")

# ── Load the config ──
try:
    from v7.core.asset_config import get_active_assets
    ASSETS = get_active_assets()
    if not ASSETS:
        ASSETS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"]
    logger.info("Loaded %d active assets", len(ASSETS))
except Exception:
    ASSETS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT"]
    logger.warning("Could not load asset config, using defaults: %s", ASSETS)


def _log_to_db(level: str, dag_id: str, node_id: str, message: str):
    """Write a log row into the dag_logs table for dashboard compatibility."""
    try:
        import sqlite3, os
        db_path = os.environ.get("DATABASE_URL", "sqlite:////app/data/v4.db")
        if db_path.startswith("sqlite:///"):
            db_path = db_path[10:]
        elif "///" in db_path:
            db_path = db_path.split("///")[-1]
        else:
            return
        conn = sqlite3.connect(db_path, timeout=10)
        # dag_logs - for the V7 dashboard (multi_asset.py)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dag_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                level TEXT DEFAULT 'INFO',
                dag_id TEXT,
                node_id TEXT,
                message TEXT
            )
        """)
        conn.execute(
            "INSERT INTO dag_logs (ts, level, dag_id, node_id, message) VALUES (?,?,?,?,?)",
            (datetime.now().isoformat(), level, dag_id, node_id, message),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # silent - the DB log is optional


def run_cycle(
    assets: list[str] | None = None,
    capital_per_asset: float = 2_000,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run one full funding carry cycle over every asset.

    Returns:
        dict with a summary (n_scanned, n_open, n_close, n_flat, errors).
    """
    from v7.nodes.funding_carry_node import FundingCarryNode
    from v7.core.asset_config import get_active_assets, reload_config

    if assets is None:
        # Reload the config on EVERY cycle: enabling/disabling an asset in
        # the dashboard (carry_assets.yaml) must take effect without restarting
        # the container. Without this reload the process cache kept the list
        # frozen at first import.
        reload_config()
        assets = get_active_assets() or ASSETS
    
    # ── Anti-concurrency lock ──
    import fcntl, os as _os
    lock_path = "/tmp/carry_cycle.lock"
    lock_fd = _os.open(lock_path, _os.O_CREAT | _os.O_RDWR, 0o644)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        logger.warning("Another carry cycle is already running — skipping")
        _os.close(lock_fd)
        return {"n_scanned": 0, "n_open": 0, "n_close": 0, "n_flat": 0,
                "n_errors": 1, "errors": ["Concurrent cycle detected — skipped"], "signals": {}}

    summary = {"n_scanned": 0, "n_open": 0, "n_close": 0, "n_flat": 0,
               "n_errors": 0, "errors": [], "signals": {}}
    t0 = time.time()

    logger.info("=" * 60)
    logger.info("CARRY CYCLE START — %d assets | Capital: $%d/asset | %s",
                len(assets), capital_per_asset,
                "DRY RUN" if dry_run else "LIVE")
    logger.info("=" * 60)

    for sym in assets:
        pfx = sym.split("/")[0].lower()[:3]
        dag_id = f"v7_{sym.split('/')[0].lower()}"
        try:
            # -- Per-asset parameters from carry_assets.yaml (fallback when absent) --
            from v7.core.asset_config import get_asset_params
            _cfg = get_asset_params(sym)
            node = FundingCarryNode(
                node_id=f"carry_{sym.split('/')[0].lower()}",
                symbol=sym,
                capital=float(_cfg.get("capital", capital_per_asset)),
                fraction=float(_cfg.get("fraction", 0.50)),
                min_funding=float(_cfg.get("min_funding", 0.00005)),
                max_funding=float(_cfg.get("max_funding", 0.003)),
                exit_after_hours=int(_cfg.get("exit_after_hours", 72)),
                max_hold_days=int(_cfg.get("max_hold_days", 14)),
                stop_loss_pct=float(_cfg.get("stop_loss_pct", -0.05)),
                params={},  # no _backtest → live mode
            )

            # Fetch prices + funding
            spot_price = node.fetch_spot_price()
            perp_price = node.fetch_perp_price()
            funding_rate = node.fetch_current_funding()

            if spot_price <= 0:
                logger.warning("  %s: spot price fetch failed, skipping", sym)
                summary["n_errors"] += 1
                summary["errors"].append(f"{sym}: spot fetch failed")
                continue

            result = node.run({
                "symbol": sym,
                "spot_price": spot_price,
                "funding_rate": funding_rate,
                "perp_price": perp_price if perp_price > 0 else spot_price,
            })

            signal = result.get("signal", "flat")
            reason = result.get("reason", "")
            summary["n_scanned"] += 1
            summary["signals"][sym] = signal

            if signal == "open_carry":
                summary["n_open"] += 1
                size = result.get("size_usd", 0)
                log_msg = f"[{sym}] OPEN CARRY | size=${size:.0f} @ ${spot_price:.4f} | {reason}"
                logger.info("  ✅ %-12s OPEN  | %s", sym, log_msg)
                _log_to_db("INFO", dag_id, f"{pfx}_carry", log_msg)
            elif signal == "close_carry":
                summary["n_close"] += 1
                log_msg = f"[{sym}] CLOSE CARRY | {reason}"
                logger.info("  🔴 %-12s CLOSE | %s", sym, log_msg)
                _log_to_db("INFO", dag_id, f"{pfx}_carry", log_msg)
            elif result.get("position_open"):
                # Active position - receiving funding -> update context_json in the DB
                log_msg = f"[{sym}] HOLD | funding received | {reason}"
                _log_to_db("INFO", dag_id, f"{pfx}_carry", log_msg)
                try:
                    import sqlite3, json as _json, os as _os2
                    db_path = _os2.environ.get("DATABASE_URL", "sqlite:////app/data/v4.db")
                    if db_path.startswith("sqlite:///"):
                        db_path = db_path[10:]
                    conn = sqlite3.connect(db_path, timeout=10)
                    # Read and update context_json with the latest values
                    rows = conn.execute(
                        "SELECT trade_id, context_json FROM v4_trades WHERE symbol=? AND status='open' AND action='carry'",
                        (sym,),
                    ).fetchall()
                    for row in rows:
                        ctx = {}
                        try:
                            ctx = _json.loads(row[1]) if row[1] else {}
                        except Exception:
                            pass
                        ctx["total_funding_received"] = result.get("total_funding_received", 0)
                        ctx["n_payments"] = result.get("n_payments", 0)
                        ctx["annual_funding_pct"] = result.get("annual_funding_pct", 0)
                        # Persist the full position state. Without it the next
                        # cycle rebuilds the node with no entry_perp, no
                        # negative_since and no funding window: the basis at entry
                        # reads as zero, the 72h timer restarts and the 7-day
                        # funding MA collapses to the current rate.
                        if result.get("carry_state"):
                            ctx["carry_state"] = result["carry_state"]
                        conn.execute(
                            "UPDATE v4_trades SET context_json=? WHERE trade_id=?",
                            (_json.dumps(ctx), row[0]),
                        )
                    conn.commit()
                    conn.close()
                except Exception:
                    pass  # best-effort
            else:
                summary["n_flat"] += 1
                log_msg = f"[{sym}] FLAT | {reason}"
                logger.debug("  ➖ %-12s flat  | %s", sym, reason)
                _log_to_db("DEBUG", dag_id, f"{pfx}_carry", log_msg)

            # -- Record the decision in the PaperTrader --
            if not dry_run and signal in ("open_carry", "close_carry"):
                decision = result.get("decision", {})
                if decision.get("action") in ("carry", "close_carry"):
                    try:
                        from storage.paper_trader import persist_trade
                        if signal == "open_carry":
                            persist_trade(
                                symbol=sym,
                                action="carry",
                                entry_price=decision.get("entry_price", spot_price),
                                stop_loss=decision.get("stop_loss", 0),
                                take_profit=decision.get("take_profit", 0),
                                size_usd=decision.get("size_usd", 0),
                                dag_id=dag_id,
                                context=decision,
                            )
                            logger.info("  💾 %s OPEN saved to DB", sym)
                        elif signal == "close_carry":
                            # Close existing position
                            from storage.paper_trader import get_open_positions
                            import sqlite3, os as _os
                            open_pos = get_open_positions(symbol=sym)
                            carry_pos = [p for p in open_pos if p.get("action") in ("carry", "short")]
                            if carry_pos:
                                db_path = _os.environ.get("DATABASE_URL", "sqlite:////app/data/v4.db")
                                if db_path.startswith("sqlite:///"):
                                    db_path = db_path[10:]
                                conn = sqlite3.connect(db_path, timeout=10)
                                import json as _json2
                                realized = float(result.get("realized_pnl_usd", 0) or 0)
                                for p in carry_pos:
                                    # Single close path: status, timestamp AND the
                                    # realised P&L, so a cycle close and a monitor
                                    # close leave the same record behind. This used
                                    # to write no pnl_usd at all, so every trade
                                    # closed by the cycle showed a P&L of zero.
                                    conn.execute(
                                        "UPDATE v4_trades SET status='closed', closed_at=?, "
                                        "pnl_usd=?, context_json=? WHERE trade_id=?",
                                        (datetime.now().isoformat(), round(realized, 4),
                                         _json2.dumps(result.get("carry_state") or {}),
                                         p.get("trade_id")),
                                    )
                                conn.commit()
                                conn.close()
                                logger.info("  💾 %s CLOSE saved to DB (%d positions, pnl=$%.2f)",
                                            sym, len(carry_pos), realized)
                    except ImportError:
                        logger.debug("  ⚠️ PaperTrader not available")
                    except Exception as e:
                        logger.error("  ❌ %s save failed: %s", sym, e)

        except Exception as e:
            logger.error("  ❌ %s: %s", sym, str(e)[:120])
            summary["n_errors"] += 1
            summary["errors"].append(f"{sym}: {str(e)[:100]}")

    elapsed = time.time() - t0
    logger.info("=" * 60)
    logger.info("CYCLE DONE in %.1fs | Scanned: %d | Open: %d | Close: %d | Flat: %d | Errors: %d",
                elapsed, summary["n_scanned"], summary["n_open"],
                summary["n_close"], summary["n_flat"], summary["n_errors"])
    logger.info("=" * 60)
    
    # Release lock
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        _os.close(lock_fd)
    except Exception:
        pass
    
    return summary


def daemon_loop(interval_hours: float = 8.0):
    """Infinite loop - runs one cycle every N hours."""
    logger.info("Starting carry daemon (interval=%.1fh). Press Ctrl+C to stop.", interval_hours)
    
    stop_flag = False
    
    def _handle_signal(sig, frame):
        nonlocal stop_flag
        logger.info("Received signal %s, stopping after current cycle...", sig)
        stop_flag = True
    
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    
    while not stop_flag:
        try:
            run_cycle()
        except Exception as e:
            logger.error("Cycle failed: %s", e, exc_info=True)
        
        if stop_flag:
            break
        
        # Wait until the next cycle (aligned on even hours)
        next_cycle = datetime.now() + timedelta(hours=interval_hours)
        logger.info("Next cycle at %s (%.1fh)", next_cycle.strftime("%H:%M"), interval_hours)
        
        # Sleep in 60s slices so we can shut down cleanly
        sleep_seconds = interval_hours * 3600
        while sleep_seconds > 0 and not stop_flag:
            time.sleep(min(60, sleep_seconds))
            sleep_seconds -= 60
    
    logger.info("Daemon stopped.")


def main():
    parser = argparse.ArgumentParser(description="V7 Funding Carry — Single cycle")
    parser.add_argument("--assets", type=str, default=None,
                       help="Comma-separated list of assets (default: all active)")
    parser.add_argument("--capital", type=float, default=2000,
                       help="Capital per asset (default: $2000)")
    parser.add_argument("--dry-run", action="store_true",
                       help="Don't save decisions to PaperTrader")
    parser.add_argument("--daemon", action="store_true",
                       help="Run continuously every 8h")
    parser.add_argument("--interval", type=float, default=8.0,
                       help="Hours between cycles in daemon mode (default: 8h)")
    args = parser.parse_args()

    assets = None
    if args.assets:
        assets = [s.strip() for s in args.assets.split(",")]

    if args.daemon:
        daemon_loop(args.interval)
    else:
        summary = run_cycle(assets=assets, capital_per_asset=args.capital, dry_run=args.dry_run)
        # Exit code based on errors
        if summary["n_errors"] > summary["n_scanned"] * 0.5:
            sys.exit(1)
        elif summary["n_errors"] > 0:
            sys.exit(0)  # some errors but not critical


if __name__ == "__main__":
    main()
