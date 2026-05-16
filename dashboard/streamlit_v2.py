"""
dashboard/streamlit_v2.py — Dashboard Atlas Trader V2

Interface minimaliste, orientée métriques quantitatives :
  - Régime courant (trending / ranging)
  - P(up) gauge
  - Décision active (LONG / SHORT / FLAT)
  - Position ouverte (entry, SL, TP, P&L latent)
  - Courbe equity OOS live
  - Table des trades récents
  - Métriques OOS clés (Sharpe, DD, Win rate)
  - Sélecteur de langue (8 langues via i18n)

Pas d opinion LLM, pas de narratif — chiffres uniquement.
Auto-refresh toutes les 30 secondes.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# --- path setup ---------------------------------------------------------------
_APP_ROOT = str(Path(__file__).resolve().parent.parent)
if _APP_ROOT not in sys.path:
    sys.path.insert(0, _APP_ROOT)

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils.i18n import t, set_lang, get_lang, SUPPORTED_LANGS
from storage.database import (
    get_v2_state,
    get_v2_equity_curve,
    get_v2_recent_trades,
    init_db,
)

# ===========================================================
# CONFIG PAGE
# ===========================================================
st.set_page_config(
    page_title="Atlas Trader V2",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Auto-refresh 30s
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=30_000, key="v2_refresh")
except ImportError:
    pass

# ===========================================================
# INIT DB (idempotent)
# ===========================================================
try:
    init_db()
except Exception:
    pass

# ===========================================================
# CSS minimal
# ===========================================================
st.markdown("""
<style>
    .metric-box {
        background: #1e2130;
        border-radius: 10px;
        padding: 16px 20px;
        text-align: center;
        margin: 4px;
    }
    .metric-label { font-size: 0.75rem; color: #8899aa; text-transform: uppercase; letter-spacing: 1px; }
    .metric-value { font-size: 2rem; font-weight: 700; margin-top: 4px; }
    .badge-trending { color: #00e676; }
    .badge-ranging  { color: #ffa726; }
    .badge-long     { color: #00e676; }
    .badge-short    { color: #ef5350; }
    .badge-flat     { color: #78909c; }
    .section-title  { font-size: 0.85rem; color: #8899aa; text-transform: uppercase;
                      letter-spacing: 2px; margin-bottom: 8px; }
    [data-testid="stMetricValue"] { font-size: 1.6rem !important; }
</style>
""", unsafe_allow_html=True)

# ===========================================================
# LANGUE
# ===========================================================
_lang_codes = list(SUPPORTED_LANGS.keys())
_lang_labels = [SUPPORTED_LANGS[c] for c in _lang_codes]
saved_lang = st.session_state.get("lang", get_lang())
_lang_idx = _lang_codes.index(saved_lang) if saved_lang in _lang_codes else 0
_selected_lang = st.sidebar.selectbox("🌐 Langue / Language", _lang_labels, index=_lang_idx)
_selected_code = _lang_codes[_lang_labels.index(_selected_lang)]
st.session_state["lang"] = _selected_code
set_lang(_selected_code)

# ===========================================================
# DONNÉES LIVE
# ===========================================================
_state = get_v2_state()
_equity_rows = get_v2_equity_curve(n=500)
_trades = get_v2_recent_trades(n=50)

# Helpers
def _flt(v, fmt=".2f"):
    return f"{v:{fmt}}" if v is not None else "—"

def _pct(v):
    return f"{v:.1%}" if v is not None else "—"

def _ts_ago(ts_str: str | None) -> str:
    if not ts_str:
        return "—"
    try:
        ts = pd.Timestamp(ts_str).tz_localize("UTC") if pd.Timestamp(ts_str).tzinfo is None else pd.Timestamp(ts_str)
        diff = pd.Timestamp.utcnow() - ts
        mins = int(diff.total_seconds() // 60)
        if mins < 2:
            return "< 1 min"
        if mins < 60:
            return f"{mins} min"
        return f"{mins // 60}h {mins % 60}m"
    except Exception:
        return ts_str[:16] if ts_str else "—"

# ===========================================================
# HEADER
# ===========================================================
col_title, col_status = st.columns([6, 2])
with col_title:
    st.markdown("## ⚡ Atlas Trader — V2 Quant")
with col_status:
    if _state:
        ago = _ts_ago(_state.get("updated_at"))
        st.markdown(f"<div style='text-align:right; color:#8899aa; padding-top:16px'>⏱ {ago}</div>",
                    unsafe_allow_html=True)
    else:
        st.markdown("<div style='text-align:right; color:#ef5350; padding-top:16px'>⚠ Aucune donnée</div>",
                    unsafe_allow_html=True)

st.divider()

# ===========================================================
# SECTION 1 — ÉTAT COURANT (régime / P(up) / décision)
# ===========================================================
st.markdown('<div class="section-title">État courant</div>', unsafe_allow_html=True)

c1, c2, c3, c4, c5 = st.columns(5)

# Régime
if _state:
    regime_val = _state.get("regime")
    regime_trending = regime_val == 1
    regime_label = "TRENDING" if regime_trending else ("RANGING" if regime_val == 0 else "—")
    regime_css = "badge-trending" if regime_trending else "badge-ranging"
    with c1:
        st.markdown(
            f'<div class="metric-box"><div class="metric-label">Régime</div>'
            f'<div class="metric-value {regime_css}">{regime_label}</div></div>',
            unsafe_allow_html=True,
        )
    # P(up)
    prob_up = _state.get("prob_up")
    prob_pct = f"{prob_up:.1%}" if prob_up is not None else "—"
    if prob_up is not None:
        prob_color = "#00e676" if prob_up > 0.55 else ("#ef5350" if prob_up < 0.45 else "#ffa726")
    else:
        prob_color = "#78909c"
    with c2:
        st.markdown(
            f'<div class="metric-box"><div class="metric-label">P(up)</div>'
            f'<div class="metric-value" style="color:{prob_color}">{prob_pct}</div></div>',
            unsafe_allow_html=True,
        )
    # Décision
    action = (_state.get("action") or "flat").lower()
    action_label = action.upper()
    action_css = {"long": "badge-long", "short": "badge-short"}.get(action, "badge-flat")
    with c3:
        st.markdown(
            f'<div class="metric-box"><div class="metric-label">Décision</div>'
            f'<div class="metric-value {action_css}">{action_label}</div></div>',
            unsafe_allow_html=True,
        )
    # Prix
    close_price = _state.get("close_price")
    with c4:
        st.markdown(
            f'<div class="metric-box"><div class="metric-label">BTC/USDT</div>'
            f'<div class="metric-value">{_flt(close_price, ",.0f")} $</div></div>',
            unsafe_allow_html=True,
        )
    # Capital
    capital = _state.get("capital")
    with c5:
        st.markdown(
            f'<div class="metric-box"><div class="metric-label">Capital</div>'
            f'<div class="metric-value">{_flt(capital, ",.0f")} $</div></div>',
            unsafe_allow_html=True,
        )
else:
    st.info("En attente des données — le daemon n'a pas encore tourné.")

st.divider()

# ===========================================================
# SECTION 2 — POSITION OUVERTE
# ===========================================================
st.markdown('<div class="section-title">Position ouverte</div>', unsafe_allow_html=True)

if _state and _state.get("position_side"):
    pos_side = _state["position_side"]
    entry = _state.get("entry_price")
    sl = _state.get("sl_price")
    tp = _state.get("tp_price")
    close = _state.get("close_price")

    # P&L latent
    if entry and close:
        if pos_side == "long":
            pnl_pct = (close - entry) / entry
        else:
            pnl_pct = (entry - close) / entry
    else:
        pnl_pct = None

    pnl_color = "#00e676" if (pnl_pct or 0) >= 0 else "#ef5350"
    side_css = "badge-long" if pos_side == "long" else "badge-short"

    pc1, pc2, pc3, pc4, pc5 = st.columns(5)
    pc1.metric("Côté", pos_side.upper())
    pc2.metric("Entry", f"{entry:,.2f} $" if entry else "—")
    pc3.metric("Stop-loss", f"{sl:,.2f} $" if sl else "—")
    pc4.metric("Take-profit", f"{tp:,.2f} $" if tp else "—")
    pc5.metric(
        "P&L latent",
        f"{pnl_pct:+.2%}" if pnl_pct is not None else "—",
        delta=f"{(close - entry):+.0f} $" if entry and close else None,
    )
else:
    st.markdown(
        '<div style="color:#78909c; padding: 10px 0">Aucune position ouverte</div>',
        unsafe_allow_html=True,
    )

st.divider()

# ===========================================================
# SECTION 3 — COURBE EQUITY
# ===========================================================
st.markdown('<div class="section-title">Courbe equity</div>', unsafe_allow_html=True)

if _equity_rows:
    eq_df = pd.DataFrame(_equity_rows)
    eq_df["ts"] = pd.to_datetime(eq_df["ts"])
    eq_df = eq_df.sort_values("ts")

    fig = go.Figure()

    # Equity curve
    fig.add_trace(go.Scatter(
        x=eq_df["ts"], y=eq_df["equity"],
        mode="lines", name="Capital",
        line=dict(color="#4fc3f7", width=2),
        fill="tozeroy", fillcolor="rgba(79,195,247,0.08)",
    ))

    # Marqueurs de trades
    entries = eq_df[eq_df["action"].isin(["long", "short"])]
    if not entries.empty:
        colors = entries["action"].map({"long": "#00e676", "short": "#ef5350"})
        symbols = entries["action"].map({"long": "triangle-up", "short": "triangle-down"})
        fig.add_trace(go.Scatter(
            x=entries["ts"], y=entries["equity"],
            mode="markers",
            marker=dict(size=8, color=colors, symbol=symbols),
            name="Entrées",
        ))

    fig.update_layout(
        height=280,
        margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False, color="#8899aa"),
        yaxis=dict(showgrid=True, gridcolor="#1e2130", color="#8899aa"),
        legend=dict(orientation="h", y=1.1, font=dict(color="#8899aa")),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)

    # Métriques synthétiques
    if len(eq_df) >= 2:
        initial = float(eq_df["equity"].iloc[0])
        final = float(eq_df["equity"].iloc[-1])
        total_ret = (final - initial) / initial
        rets = eq_df["equity"].pct_change().dropna()
        sharpe = float(rets.mean() / rets.std() * (365 * 96) ** 0.5) if rets.std() > 0 else 0.0
        cummax = eq_df["equity"].cummax()
        max_dd = float(((eq_df["equity"] - cummax) / cummax).min())

        m1, m2, m3, m4 = st.columns(4)
        delta_color = "normal" if total_ret >= 0 else "inverse"
        m1.metric("Rendement total", _pct(total_ret))
        m2.metric("Sharpe annualisé", f"{sharpe:.2f}")
        m3.metric("Max drawdown", _pct(max_dd))
        n_trades = len(_trades)
        m4.metric("Trades total", str(n_trades))
else:
    st.info("Pas encore de données equity — le daemon n'a pas encore tourné.")

st.divider()

# ===========================================================
# SECTION 4 — TRADES RÉCENTS
# ===========================================================
st.markdown('<div class="section-title">Trades récents</div>', unsafe_allow_html=True)

if _trades:
    tdf = pd.DataFrame(_trades)
    tdf["ts"] = pd.to_datetime(tdf["ts"]).dt.strftime("%d/%m/%Y %H:%M")
    tdf = tdf.rename(columns={
        "ts": "Horodatage",
        "action": "Côté",
        "close_price": "Prix",
        "equity": "Capital après",
    })
    tdf["Côté"] = tdf["Côté"].str.upper()
    st.dataframe(
        tdf[["Horodatage", "Côté", "Prix", "Capital après"]],
        use_container_width=True,
        hide_index=True,
    )
else:
    st.markdown('<div style="color:#78909c">Aucun trade enregistré.</div>', unsafe_allow_html=True)

st.divider()

# ===========================================================
# SECTION 5 — INFOS MODÈLE
# ===========================================================
with st.expander("Informations modèle V2", expanded=False):
    if _state:
        st.markdown(f"""
| Champ | Valeur |
|---|---|
| Asset | `{_state.get('asset', '—')}` |
| Dernière barre | `{str(_state.get('bar_ts', '—'))[:16]}` |
| Dernier refit | `{str(_state.get('model_fit_at', '—'))[:16]}` |
| ATR-14 | `{_flt(_state.get('atr_14'))}` |
| Raison décision | `{_state.get('reason', '—')}` |
        """)
    else:
        st.info("Aucun état disponible.")

    st.markdown("""
**Règles de décision V2 (auditables) :**
- Trader seulement si régime **TRENDING** (HMM filtering ou ADX + vol_of_vol)
- **LONG** si P(up) > 0.55
- **SHORT** si P(up) < 0.45
- **FLAT** sinon (zone morte) ou si régime ranging

**Gestion du risque :**
- Sizing : 1.5% du capital / distance_SL
- Stop-loss : 2.5 × ATR₁₄
- Take-profit : 3.0 × ATR₁₄ (R:R ≈ 1.2)
- Trailing stop : activé après +1 ATR, recule de 1 ATR
- Kill-switch : pause 7 jours si DD hebdo > 8%
    """)

# ===========================================================
# FOOTER
# ===========================================================
st.markdown(
    '<div style="color:#374151; font-size:0.7rem; text-align:center; margin-top:20px">'
    f'Atlas Trader V2 — Quant Core — {datetime.utcnow().strftime("%d/%m/%Y %H:%M")} UTC'
    '</div>',
    unsafe_allow_html=True,
)
