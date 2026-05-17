"""
backtest/report.py — Génération du rapport HTML de performance.

Métriques calculées par actif et globalement :
  - Sharpe ratio annualisé
  - Max drawdown ($)
  - Win rate (%)
  - Profit factor
  - P&L total ($)
  - Distribution des actions (BUY/SELL/HOLD)
  - Courbe de P&L cumulé
  - Heatmap score vs résultat
  - Tableau des meilleures/pires trades
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backtest.sim_engine import SimTrade


# ── Helpers ────────────────────────────────────────────────────────────────

def _color_pnl(value: float) -> str:
    if value > 0:
        return f'<span style="color:#27ae60;font-weight:bold">${value:+.2f}</span>'
    elif value < 0:
        return f'<span style="color:#e74c3c;font-weight:bold">${value:+.2f}</span>'
    return f"${value:.2f}"


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _badge(text: str, color: str) -> str:
    return f'<span style="background:{color};color:#fff;padding:2px 8px;border-radius:4px;font-size:0.85em">{text}</span>'


# ── Courbe P&L cumulé (inline SVG sparkline) ─────────────────────────────

    active = [t for t in trades if t.action in ("LONG", "SHORT") and t.result_24h is not None]
    if not active:
        return "<em>Aucune transaction active</em>"

    cumulative = []
    total = 0.0
    for t in active:
        total += t.result_24h
        cumulative.append(total)

    min_v = min(cumulative)
    max_v = max(cumulative)
    rng = max_v - min_v if max_v != min_v else 1.0

    n = len(cumulative)
    points = []
    for i, v in enumerate(cumulative):
        x = int(i / max(n - 1, 1) * (width - 10)) + 5
        y = int((1 - (v - min_v) / rng) * (height - 10)) + 5
        points.append(f"{x},{y}")

    # Couleur selon résultat final
    final_color = "#27ae60" if cumulative[-1] >= 0 else "#e74c3c"
    polyline = f'<polyline points="{" ".join(points)}" fill="none" stroke="{final_color}" stroke-width="2"/>'

    # Ligne zéro
    y_zero = int((1 - (0 - min_v) / rng) * (height - 10)) + 5
    zero_line = f'<line x1="5" y1="{y_zero}" x2="{width-5}" y2="{y_zero}" stroke="#7f8c8d" stroke-width="1" stroke-dasharray="4"/>'

    return (
        f'<svg width="{width}" height="{height}" style="border:1px solid #ecf0f1;border-radius:4px;background:#fafafa">'
        f'{zero_line}{polyline}'
        f'</svg>'
    )


# ── Tableau des top trades ────────────────────────────────────────────────

    active = [t for t in trades if t.action in ("LONG", "SHORT") and t.result_24h is not None]
    if not active:
        return "<em>Aucune transaction</em>"

    sorted_trades = sorted(active, key=lambda t: t.result_24h, reverse=best)[:n]
    label = "Meilleures" if best else "Pires"

    rows = ""
    for t in sorted_trades:
        ts = t.timestamp.strftime("%Y-%m-%d %H:%M") if t.timestamp else "?"
        action_badge = _badge(t.action, "#27ae60" if t.action == "LONG" else "#e74c3c")
        rows += f"""<tr>
            <td>{t.asset}</td>
            <td>{ts}</td>
            <td>{action_badge}</td>
            <td>{t.score:.1f}</td>
            <td>${t.entry_price:.4f}</td>
            <td>{t.regime}</td>
            <td>{_color_pnl(t.result_24h)}</td>
        </tr>"""

    return f"""
    <h4>{label} trades</h4>
    <table class="bt-table">
        <thead><tr>
            <th>Actif</th><th>Horodatage</th><th>Action</th>
            <th>Score</th><th>Prix entrée</th><th>Régime</th><th>P&amp;L 24h</th>
        </tr></thead>
        <tbody>{rows}</tbody>
    </table>"""


# ── Carte par actif ────────────────────────────────────────────────────────

def _asset_card(symbol: str, trades: list[SimTrade], metrics: dict) -> str:
    pnl_color = "#27ae60" if metrics["total_pnl"] >= 0 else "#e74c3c"
    sparkline = _pnl_sparkline(trades)

    regime_counts: dict[str, int] = {}
    for t in trades:
        regime_counts[t.regime] = regime_counts.get(t.regime, 0) + 1
    regime_str = " | ".join(f"{r}: {c}" for r, c in sorted(regime_counts.items()))

    return f"""
    <div class="asset-card">
        <h3>{symbol}</h3>
        <div class="metrics-grid">
            <div class="metric"><div class="metric-label">Cycles</div><div class="metric-value">{metrics['total_cycles']}</div></div>
            <div class="metric"><div class="metric-label">LONG / SHORT / FLAT</div><div class="metric-value">{metrics['n_buy']} / {metrics['n_sell']} / {metrics['n_hold']}</div></div>
            <div class="metric"><div class="metric-label">Win Rate</div><div class="metric-value">{_fmt_pct(metrics['win_rate'])}</div></div>
            <div class="metric"><div class="metric-label">P&amp;L Total</div><div class="metric-value" style="color:{pnl_color}">${metrics['total_pnl']:+.2f}</div></div>
            <div class="metric"><div class="metric-label">Sharpe (annualisé)</div><div class="metric-value">{metrics['sharpe']:.3f}</div></div>
            <div class="metric"><div class="metric-label">Max Drawdown</div><div class="metric-value" style="color:#e74c3c">${metrics['max_drawdown']:.2f}</div></div>
            <div class="metric"><div class="metric-label">Profit Factor</div><div class="metric-value">{metrics['profit_factor']:.2f}</div></div>
        </div>
        <div style="margin:12px 0"><strong>Régimes :</strong> {regime_str or "N/A"}</div>
        <div><strong>Courbe P&amp;L cumulé :</strong></div>
        <div style="margin:8px 0">{sparkline}</div>
        {_top_trades_table(trades, 5, best=True)}
        {_top_trades_table(trades, 5, best=False)}
    </div>"""


# ── HTML global ────────────────────────────────────────────────────────────

_CSS = """
<style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; background: #f0f2f5; color: #2c3e50; }
    .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
    .header { background: linear-gradient(135deg, #1a1a2e, #16213e); color: #fff; padding: 30px; border-radius: 12px; margin-bottom: 24px; }
    .header h1 { margin: 0 0 8px; font-size: 1.8em; }
    .header .subtitle { color: #95a5a6; font-size: 0.9em; }
    .summary-banner { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 24px; }
    .summary-item { flex: 1; min-width: 150px; background: #fff; border-radius: 8px; padding: 16px; text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,.07); }
    .summary-item .val { font-size: 1.8em; font-weight: 700; }
    .summary-item .lbl { font-size: 0.8em; color: #7f8c8d; text-transform: uppercase; letter-spacing: .05em; margin-top: 4px; }
    .asset-card { background: #fff; border-radius: 10px; padding: 24px; margin-bottom: 20px; box-shadow: 0 2px 10px rgba(0,0,0,.08); }
    .asset-card h3 { margin: 0 0 16px; font-size: 1.3em; border-bottom: 2px solid #3498db; padding-bottom: 8px; }
    .metrics-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; margin-bottom: 16px; }
    .metric { background: #f8f9fa; border-radius: 6px; padding: 12px; }
    .metric-label { font-size: 0.75em; color: #7f8c8d; text-transform: uppercase; margin-bottom: 4px; }
    .metric-value { font-size: 1.1em; font-weight: 600; }
    .bt-table { width: 100%; border-collapse: collapse; font-size: 0.88em; margin-top: 12px; }
    .bt-table th { background: #2c3e50; color: #fff; padding: 8px 10px; text-align: left; }
    .bt-table td { padding: 7px 10px; border-bottom: 1px solid #ecf0f1; }
    .bt-table tr:nth-child(even) td { background: #f8f9fa; }
    .notice { background: #fff3cd; border: 1px solid #ffc107; border-radius: 6px; padding: 12px 16px; margin-bottom: 20px; font-size: 0.9em; }
    footer { text-align: center; color: #95a5a6; font-size: 0.8em; margin-top: 30px; padding: 20px; }
</style>
"""


def generate_report(
    run_id: str,
    trades: list[SimTrade],
    metrics_by_symbol: dict[str, dict],
    output_path: Path | None = None,
) -> Path:
    """
    Génère un rapport HTML complet.
    Retourne le chemin du fichier créé.
    """
    if output_path is None:
        output_path = Path(__file__).parent / "backtest_report.html"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Métriques globales agrégées
    all_active = [t for t in trades if t.action in ("LONG", "SHORT") and t.result_24h is not None]
    total_pnl = sum(t.result_24h for t in all_active)
    total_cycles = len(trades)
    total_buy = sum(1 for t in trades if t.action == "LONG")
    avg_win_rate = (
        sum(m["win_rate"] for m in metrics_by_symbol.values()) / len(metrics_by_symbol)
        if metrics_by_symbol else 0.0
    )
    best_asset = max(metrics_by_symbol.items(), key=lambda kv: kv[1]["sharpe"])[0] if metrics_by_symbol else "N/A"

    pnl_color = "#27ae60" if total_pnl >= 0 else "#e74c3c"

    summary_banner = f"""
    <div class="summary-banner">
        <div class="summary-item">
            <div class="val">{total_cycles}</div>
            <div class="lbl">Cycles simulés</div>
        </div>
        <div class="summary-item">
            <div class="val">{total_buy}</div>
            <div class="lbl">Trades BUY</div>
        </div>
        <div class="summary-item">
            <div class="val" style="color:{pnl_color}">${total_pnl:+.2f}</div>
            <div class="lbl">P&L global</div>
        </div>
        <div class="summary-item">
            <div class="val">{_fmt_pct(avg_win_rate)}</div>
            <div class="lbl">Win Rate moyen</div>
        </div>
        <div class="summary-item">
            <div class="val">{best_asset}</div>
            <div class="lbl">Meilleur actif (Sharpe)</div>
        </div>
    </div>"""

    asset_sections = ""
    for sym in sorted(metrics_by_symbol.keys()):
        sym_trades = [t for t in trades if t.asset == sym]
        asset_sections += _asset_card(sym, sym_trades, metrics_by_symbol[sym])

    notice = """
    <div class="notice">
        <strong>⚠ Limites du backtest :</strong>
        SynthesisAgent (LLM), X/Twitter sentiment et broad web crawler sont <strong>neutralisés</strong>
        (score = 50). Les résultats reflètent la performance des agents quantitatifs uniquement.
        Le ContrarianAgent (L/S ratio Binance) est également neutralisé faute d'historique.
        Fear &amp; Greed provient de alternative.me — disponible depuis ~2018 seulement.
        Ces résultats ne constituent pas un conseil financier.
    </div>"""

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Atlas BacktestRunner — {run_id}</title>
    {_CSS}
</head>
<body>
<div class="container">
    <div class="header">
        <h1>Atlas BacktestRunner</h1>
        <div class="subtitle">Run : {run_id} | Généré le {now}</div>
        <div class="subtitle">Actifs : {", ".join(sorted(metrics_by_symbol.keys()))}</div>
    </div>
    {notice}
    {summary_banner}
    {asset_sections}
    <footer>Atlas Trader — Backtest quantitatif standalone. LLM neutralisé.</footer>
</div>
</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")
    return output_path
