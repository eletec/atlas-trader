"""
dashboard/flux_manager.py — Interface de gestion des flux en temps réel
Page Streamlit dédiée au monitoring et contrôle de chaque flux de données.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import streamlit as st

try:
    from utils.i18n import t
except ImportError:
    from i18n import t  # type: ignore

# ===========================================================
# CONFIGURATION DES FLUX
# ===========================================================

# Pipeline V2 — étapes exécutées séquentiellement par LiveRunner chaque cycle.
FLUX_DEFINITIONS = {
    "ohlcv_loader": {
        "label": "📊 OHLCV Loader",
        "description": "CCXT — chargement OHLCV (timeframe configurable, cache disque)",
        "category": "data",
        "sla_latency_ms": 5000,
        "config_key": "exchange",
    },
    "features": {
        "label": "⚙ Feature Engineering",
        "description": "log_return, ATR, ADX, MA50, vol_z — calcul causal",
        "category": "processing",
        "sla_latency_ms": 500,
        "config_key": "quant",
    },
    "regime": {
        "label": "⊞ Régime Marché",
        "description": "ADX + volatilité (HMM optionnel) — filtre trending/ranging",
        "category": "processing",
        "sla_latency_ms": 500,
        "config_key": "quant",
    },
    "signal_model": {
        "label": "🧠 Signal Model",
        "description": "LogisticRegression + Platt scaling — P(up) / P(dn)",
        "category": "processing",
        "sla_latency_ms": 200,
        "config_key": "quant",
    },
    "strategy": {
        "label": "📐 Stratégie V2",
        "description": "Décision LONG/SHORT/HOLD selon régime × P(up)",
        "category": "decision",
        "sla_latency_ms": 100,
        "config_key": "quant",
    },
    "risk": {
        "label": "⚖ Risk Manager",
        "description": "Position sizing ATR — SL/TP, Kelly, max drawdown",
        "category": "decision",
        "sla_latency_ms": 100,
        "config_key": "risk",
    },
    "paper_trader": {
        "label": "⚡ Paper Trader",
        "description": "Exécution simulée CCXT (testnet/paper)",
        "category": "execution",
        "sla_latency_ms": 3000,
        "config_key": "exchange",
    },
}

CATEGORY_COLORS = {
    "data":       "#1f77b4",   # bleu
    "processing": "#2ca02c",   # vert
    "decision":   "#ff7f0e",   # orange
    "execution":  "#d62728",   # rouge
}

# CATEGORY_LABELS are resolved at render time via t() — see render_status_board()
CATEGORY_LABEL_KEYS = {
    "data":       "flux_cat_data",
    "processing": "flux_cat_processing",
    "decision":   "flux_cat_decision",
    "execution":  "flux_cat_execution",
}

# Correspondance flux_name → module(s) logger réel dans SQLite
# Certains modules V2 utilisent un nom de logger différent du flux_name.
FLUX_LOG_MODULES = {
    "ohlcv_loader": ["zeitgeist.quant.data_loader"],
    "features":     ["zeitgeist.quant.pipeline", "zeitgeist.quant.features"],
    "regime":       ["zeitgeist.quant.regime"],
    "signal_model": ["zeitgeist.quant.signal_model"],
    "strategy":     ["zeitgeist.quant.strategy", "zeitgeist.quant.workflow"],
    "risk":         ["zeitgeist.quant.risk"],
    "paper_trader": ["zeitgeist.paper_trader", "zeitgeist.execution.paper_trader"],
}

STATUS_ICONS = {
    "ok": "🟢",
    "hold": "🟢",
    "error": "🔴",
    "timeout": "🟡",
    "disabled": "⚫",
    "pending": "🔵",
    "unknown": "⚪",
}


# ===========================================================
# CHARGEMENT DES DONNÉES
# ===========================================================

def _get_db():
    """Retourne une connexion SQLite directe."""
    try:
        import sqlite3
        from storage.database import _DB_PATH
        conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        return None


def load_flux_metrics(flux_name: str | None = None, hours: int = 1) -> pd.DataFrame:
    """
    Charge les métriques de flux depuis SQLite.
    Retourne un DataFrame vide si la DB n'est pas disponible (mode démo).
    """
    conn = _get_db()
    if conn is None:
        return _generate_demo_metrics(flux_name, hours)

    since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    query = """
        SELECT timestamp, flux_name, status, latency_ms, items_count, error_message
        FROM flux_metrics
        WHERE timestamp > ?
        {}
        ORDER BY timestamp DESC
    """.format("AND flux_name = ?" if flux_name else "")

    params = (since, flux_name) if flux_name else (since,)
    try:
        df = pd.read_sql_query(query, conn, params=params)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df
    except Exception:
        return _generate_demo_metrics(flux_name, hours)
    finally:
        conn.close()


def _infer_v2_status() -> dict[str, dict]:
    """Infère le statut des composants V2 depuis v2_state (V2 n'écrit pas dans flux_metrics).

    Retourne 'pending' pour tous les flux si la DB est disponible mais qu'aucun
    cycle n'a encore écrit dans v2_state (premier démarrage).
    """
    _pending_all = {
        k: {"status": "pending", "latency_ms": 0, "timestamp": "—", "items_count": 0}
        for k in FLUX_DEFINITIONS
    }
    try:
        from storage.database import get_v2_state
        state = get_v2_state()
    except Exception:
        return {}   # DB inaccessible — laisser le caller décider
    if not state or not state.get("updated_at"):
        # DB ok mais aucun cycle exécuté encore → pending (pas unknown)
        return _pending_all
    try:
        age_s = (datetime.utcnow() - datetime.fromisoformat(state["updated_at"])).total_seconds()
    except Exception:
        return _pending_all
    ts = state["updated_at"]
    has_price   = bool(state.get("close_price"))
    has_signal  = state.get("prob_up") is not None
    has_action  = bool(state.get("action"))
    has_capital = bool(state.get("capital"))

    # < 30 min → ok ; 30 min–2 h → timeout (orange) ; > 2 h → unknown
    if age_s < 1800:
        health = "ok"
    elif age_s < 7200:
        health = "timeout"
    else:
        health = "unknown"

    def _s(has_data: bool) -> str:
        return health if has_data else "pending"

    return {
        "ohlcv_loader": {"status": _s(has_price),   "latency_ms": 0, "timestamp": ts, "items_count": 1},
        "features":     {"status": _s(has_signal),  "latency_ms": 0, "timestamp": ts, "items_count": 1},
        "regime":       {"status": _s(has_signal),  "latency_ms": 0, "timestamp": ts, "items_count": 1},
        "signal_model": {"status": _s(has_signal),  "latency_ms": 0, "timestamp": ts, "items_count": 1},
        "strategy":     {"status": _s(has_action),  "latency_ms": 0, "timestamp": ts, "items_count": 1},
        "risk":         {"status": _s(has_capital), "latency_ms": 0, "timestamp": ts, "items_count": 1},
        "paper_trader": {"status": health,           "latency_ms": 0, "timestamp": ts, "items_count": 1},
    }


def load_last_status_per_flux() -> dict[str, dict]:
    """Récupère le dernier statut de chaque flux."""
    conn = _get_db()
    if conn is None:
        return _infer_v2_status() or _generate_demo_status()

    query = """
        SELECT flux_name, status, latency_ms, items_count, timestamp, error_message
        FROM flux_metrics
        WHERE (flux_name, timestamp) IN (
            SELECT flux_name, MAX(timestamp) FROM flux_metrics GROUP BY flux_name
        )
    """
    try:
        df = pd.read_sql_query(query, conn)
        if df.empty:
            # flux_metrics vide → inférer entièrement depuis v2_state
            return _infer_v2_status() or _generate_demo_status()
        # Filtrer aux flux V2 connus (évite les entrées V1 résiduelles)
        result = df.set_index("flux_name").to_dict("index")
        known = {k: v for k, v in result.items() if k in FLUX_DEFINITIONS}
        # Compléter les flux V2 absents de flux_metrics (ex: restes V1 paper_trader)
        v2_inf = _infer_v2_status()
        for flux_name in FLUX_DEFINITIONS:
            if flux_name not in known and flux_name in v2_inf:
                known[flux_name] = v2_inf[flux_name]
        return known
    except Exception:
        return _infer_v2_status() or _generate_demo_status()
    finally:
        conn.close()


def load_flux_stats(hours: int = 24) -> dict[str, dict]:
    """Calcule les stats agrégées (taux erreur, latence moy) sur N heures."""
    df = load_flux_metrics(hours=hours)
    if df.empty:
        return {}

    stats = {}
    for flux_name, group in df.groupby("flux_name"):
        if flux_name not in FLUX_DEFINITIONS:
            continue  # ignorer les flux V1 résiduels
        total = len(group)
        errors = len(group[group["status"] == "error"])
        stats[flux_name] = {
            "total_calls": total,
            "error_rate_pct": round(errors / total * 100, 1) if total > 0 else 0,
            "avg_latency_ms": round(group["latency_ms"].mean(), 0),
            "p95_latency_ms": round(group["latency_ms"].quantile(0.95), 0),
            "total_items": group["items_count"].sum(),
        }
    return stats


# ===========================================================
# CONTRÔLES DES FLUX
# ===========================================================

def _get_settings():
    """Charge les settings YAML."""
    try:
        from utils.config import load_settings
        return load_settings()
    except ImportError:
        return {}


def _save_settings(settings: dict) -> bool:
    """Sauvegarde les settings YAML."""
    try:
        from utils.config import save_settings
        save_settings(settings)
        return True
    except ImportError:
        st.warning(t("flux_demo_save"))
        return False
    except PermissionError as exc:
        st.error(f"Permission refusée — {exc}\n\n**Sur GX10 :** `chmod 666 /app/config/settings.gx10.yaml`")
        return False


def is_flux_enabled(flux_name: str, settings: dict) -> bool:
    """Vérifie si un flux est activé dans la config."""
    cfg_key = FLUX_DEFINITIONS.get(flux_name, {}).get("config_key", "")
    if "." in cfg_key:
        parts = cfg_key.split(".")
        section = settings.get(parts[0], {})
        return section.get(parts[1], {}).get("enabled", True)
    return True


def toggle_flux(flux_name: str, enabled: bool, settings: dict) -> dict:
    """Active ou désactive un flux dans la config."""
    cfg_key = FLUX_DEFINITIONS.get(flux_name, {}).get("config_key", "")
    if "." in cfg_key:
        parts = cfg_key.split(".")
        if parts[0] not in settings:
            settings[parts[0]] = {}
        if parts[1] not in settings[parts[0]]:
            settings[parts[0]][parts[1]] = {}
        settings[parts[0]][parts[1]]["enabled"] = enabled
    return settings


# ===========================================================
# COMPOSANTS UI
# ===========================================================

def render_pipeline_diagram(statuses: dict[str, dict]) -> None:
    """Diagramme du pipeline V2 quantitatif avec statuts colorés via Graphviz."""
    def _color(flux_name: str) -> str:
        s = statuses.get(flux_name, {}).get("status", "unknown")
        return {"ok": "#2ecc71", "hold": "#2ecc71", "error": "#e74c3c", "timeout": "#f3a10c",
                "disabled": "#5a6268", "unknown": "#495057"}.get(s, "#495057")

    def _lbl(flux_name: str, short: str) -> str:
        s = statuses.get(flux_name, {}).get("status", "unknown")
        icon = {"ok": "OK", "error": "ERR", "timeout": "TMO",
                "disabled": "OFF", "unknown": "?", "hold": "OK"}.get(s, "?")
        return short + "\\n[" + icon + "]"

    # Pré-calcul des labels et couleurs (backslash interdit dans les {} d'un f-string < Py3.12)
    lbl_ol = _lbl("ohlcv_loader", "OHLCV\\nLoader")
    lbl_fe = _lbl("features", "Features")
    lbl_re = _lbl("regime", "Regime")
    lbl_sm = _lbl("signal_model", "Signal\\nModel")
    lbl_st = _lbl("strategy", "Strategie")
    lbl_rk = _lbl("risk", "Risk\\nManager")
    lbl_pt = _lbl("paper_trader", "Paper\\nTrader")
    clr_ol = _color("ohlcv_loader")
    clr_fe = _color("features")
    clr_re = _color("regime")
    clr_sm = _color("signal_model")
    clr_st = _color("strategy")
    clr_rk = _color("risk")
    clr_pt = _color("paper_trader")

    dot = f"""
digraph pipeline_v2 {{
    rankdir=LR
    bgcolor="#0e1117"
    node [shape=box, style="filled,rounded", fontcolor="white", fontname="Helvetica", fontsize=10]
    edge [color="#7986cb", arrowsize=0.8, penwidth=1.4]

    subgraph cluster_DATA {{
        label="Donnees"
        style=filled
        fillcolor="#10192a"
        color="#1f77b4"
        fontcolor="#7bb8e8"
        fontname="Helvetica-Bold"
        OL [label="{lbl_ol}", fillcolor="{clr_ol}"]
    }}

    subgraph cluster_PROC {{
        label="Traitement"
        style=filled
        fillcolor="#0a1a0a"
        color="#2ca02c"
        fontcolor="#7bc87b"
        fontname="Helvetica-Bold"
        FE [label="{lbl_fe}", fillcolor="{clr_fe}"]
        RE [label="{lbl_re}", fillcolor="{clr_re}"]
        SM [label="{lbl_sm}", fillcolor="{clr_sm}"]
    }}

    subgraph cluster_DEC {{
        label="Decision"
        style=filled
        fillcolor="#1a120a"
        color="#ff7f0e"
        fontcolor="#ffb87b"
        fontname="Helvetica-Bold"
        ST [label="{lbl_st}", fillcolor="{clr_st}"]
        RK [label="{lbl_rk}", fillcolor="{clr_rk}"]
    }}

    subgraph cluster_EXE {{
        label="Execution"
        style=filled
        fillcolor="#1a0a0a"
        color="#d62728"
        fontcolor="#e87b7b"
        fontname="Helvetica-Bold"
        PT [label="{lbl_pt}", fillcolor="{clr_pt}"]
    }}

    OL -> FE
    FE -> RE
    FE -> SM
    RE -> ST [label="filtre", style=dashed, color="#7986cb"]
    SM -> ST [label="P(up)"]
    ST -> RK
    RK -> PT
}}
"""
    st.graphviz_chart(dot, use_container_width=True)


def render_status_board(statuses: dict[str, dict], stats: dict[str, dict],
                         settings: dict) -> None:
    """Tableau de statut temps réel de chaque étape du pipeline V2."""
    categories = ["data", "processing", "decision", "execution"]

    for cat in categories:
        fluxes_in_cat = [
            (k, v) for k, v in FLUX_DEFINITIONS.items() if v["category"] == cat
        ]
        if not fluxes_in_cat:
            continue

        st.markdown(
            f"<h4 style='color:{CATEGORY_COLORS[cat]}'>"
            f"{t(CATEGORY_LABEL_KEYS[cat])}</h4>",
            unsafe_allow_html=True
        )

        _MAX_COLS = 4
        _chunks = [
            fluxes_in_cat[i:i + _MAX_COLS]
            for i in range(0, len(fluxes_in_cat), _MAX_COLS)
        ]
        for _chunk in _chunks:
            cols = st.columns(_MAX_COLS)
            for col, (flux_name, flux_def) in zip(cols, _chunk):
                with col:
                    status_info = statuses.get(flux_name, {})
                    stat_info = stats.get(flux_name, {})
                    status = status_info.get("status", "unknown")
                    enabled = is_flux_enabled(flux_name, settings)

                    if not enabled:
                        status = "disabled"

                    icon = STATUS_ICONS.get(status, "⚪")
                    latency = status_info.get("latency_ms", 0)
                    sla = flux_def["sla_latency_ms"]
                    last_ts = status_info.get("timestamp", "—")
                    if last_ts and last_ts != "—":
                        try:
                            dt = datetime.fromisoformat(str(last_ts))
                            ago = int((datetime.utcnow() - dt).total_seconds())
                            last_ts = f"{ago}s ago" if ago < 3600 else f"{ago//3600}h ago"
                        except Exception:
                            pass

                    err_rate = stat_info.get("error_rate_pct", 0)
                    latency_color = "normal" if latency <= sla else "inverse"

                    with st.container(border=True):
                        st.markdown(f"**{icon} {flux_def['label']}**")
                        st.caption(t(f"flux_desc_{flux_name}"))
                        st.metric(t("flux_latency"), f"{latency}ms", delta=None,
                                  delta_color=latency_color)
                        c1, c2 = st.columns(2)
                        c1.metric(t("flux_errors"), f"{err_rate}%")
                        c2.metric("Items/h", f"{stat_info.get('total_items', 0)}")
                        st.caption(t("flux_last_call").format(ts=last_ts))

                        if status == "error" and status_info.get("error_message"):
                            st.error(f"⚠️ {status_info['error_message'][:80]}",
                                     icon="🚨")


def render_controls(settings: dict) -> dict | None:
    """Panneau de contrôle V2 — actifs actifs + paramètres globaux."""
    st.markdown(f'<h4><i class="fas fa-sliders" style="margin-right:7px;color:#7986cb;"></i>{t("flux_controls_title")}</h4>', unsafe_allow_html=True)

    st.info(
        "🔬 **V2 Pipeline** — le pipeline quantitatif s'exécute comme une unité (pas de toggle par étape). "
        "Pour configurer les seuils et le timeframe, utilisez l'onglet **Moteur Quant V2**. "
        "Pour le capital et le risk par actif, utilisez **Par Actif**."
    )

    # Actifs actifs — seul vrai contrôle V2 ici
    st.markdown("#### Actifs surveillés")
    proj = settings.get("project", {})
    _pa_opts = proj.get("active_assets", ["BTC/USDT"])
    _pa_new = st.multiselect(
        "Actifs actifs (pipeline V2)",
        options=_pa_opts + ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XAU/USD",
                            "XAG/USD", "WTI/USD", "GBP/USD", "EUR/USD"],
        default=_pa_opts,
        key="flux_ctrl_active_assets",
        help="Le daemon itère sur tous ces actifs à chaque cycle (voir Intervalle cycle).",
    )

    st.markdown("#### Paper Trading")
    exch = settings.get("exchange", {})
    _testnet = st.toggle("Mode testnet", value=exch.get("testnet", True),
                         key="flux_ctrl_testnet")

    st.markdown("#### Paramètres pipeline")
    qcfg = settings.get("quant", {})
    _tf_cur = qcfg.get("timeframe", "5m")
    _tf_secs = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400}
    _recommended_interval = _tf_secs.get(_tf_cur, 300)
    col1, col2 = st.columns(2)
    with col1:
        _ival = settings.get("project", {}).get("loop_interval_seconds", 900)
        _ival_new = st.number_input(
            "Intervalle cycle (s)", 60, 3600, int(_ival), 60,
            key="flux_ctrl_interval",
            help=f"Fréquence de réveil du daemon. **Recommandé : {_recommended_interval}s** pour le timeframe {_tf_cur} (1 décision par barre fermée).",
        )
        if _ival_new != _recommended_interval:
            st.caption(f"⚠️ Recommandé : **{_recommended_interval}s** pour TF {_tf_cur}. Valeur actuelle = {_ival_new}s — le bot agira sur {_ival_new // _recommended_interval if _recommended_interval else '?'}éme barre seulement.")
    with col2:
        _hmm = qcfg.get("use_hmm", False)
        _hmm_new = st.toggle("Utiliser HMM", value=_hmm, key="flux_ctrl_hmm",
                             help="Active le filtre HMM (hmmlearn requis).")

    changed = (
        set(_pa_new) != set(_pa_opts)
        or _testnet != exch.get("testnet", True)
        or _ival_new != _ival
        or _hmm_new != _hmm
    )
    if not changed:
        return None

    updated = dict(settings)
    updated.setdefault("project", {})["active_assets"] = _pa_new
    updated.setdefault("exchange", {})["testnet"] = _testnet
    updated.setdefault("project", {})["loop_interval_seconds"] = int(_ival_new)
    updated.setdefault("quant", {})["use_hmm"] = _hmm_new
    return updated


def render_latency_chart(flux_name: str, hours: int = 1) -> None:
    """Graphique de latence pour un flux donné."""
    import plotly.graph_objects as go

    df = load_flux_metrics(flux_name=flux_name, hours=hours)
    if df.empty:
        st.info(t("flux_no_data"))
        return

    sla = FLUX_DEFINITIONS.get(flux_name, {}).get("sla_latency_ms", 10000)
    df_ok = df[df["status"] == "ok"]
    df_err = df[df["status"] == "error"]

    fig = go.Figure()
    if not df_ok.empty:
        fig.add_trace(go.Scatter(
            x=df_ok["timestamp"], y=df_ok["latency_ms"],
            mode="lines+markers", name=t("flux_latency_ok"),
            line=dict(color="#2ecc71"), marker=dict(size=4)
        ))
    if not df_err.empty:
        fig.add_trace(go.Scatter(
            x=df_err["timestamp"], y=df_err["latency_ms"],
            mode="markers", name=t("flux_errors"),
            marker=dict(color="#e74c3c", size=8, symbol="x")
        ))
    fig.add_hline(
        y=sla, line_dash="dash", line_color="#f39c12",
        annotation_text=f"SLA {sla}ms"
    )
    fig.update_layout(
        title=t("flux_latency_title").format(label=FLUX_DEFINITIONS.get(flux_name, {}).get('label', flux_name)),
        xaxis_title=t("flux_x_axis"), yaxis_title=t("flux_y_axis"),
        height=300, margin=dict(l=0, r=0, t=40, b=0),
        plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
        font=dict(color="#ffffff")
    )
    st.plotly_chart(fig, use_container_width=True)


def render_flux_logs(flux_name: str | None, limit: int = 50) -> None:
    """Logs filtrés par flux — utilise FLUX_LOG_MODULES pour mapper flux_name → logger réel."""
    conn = _get_db()
    if conn is None:
        st.info(t("flux_logs_unavailable"))
        return

    if flux_name:
        # Résoudre les modules réels depuis le mapping, avec fallback sur %flux_name%
        modules = FLUX_LOG_MODULES.get(flux_name, [f"%{flux_name}%"])
        # Construire une clause OR pour tous les modules du flux
        or_clauses = " OR ".join("module LIKE ?" for _ in modules)
        where_clause = f"AND ({or_clauses})"
        params: tuple = tuple(m if "%" in m else f"%{m}%" for m in modules) + (limit,)
    else:
        where_clause = ""
        params = (limit,)

    query = f"""
        SELECT timestamp, level, module, message
        FROM logs
        WHERE 1=1
        {where_clause}
        ORDER BY timestamp DESC
        LIMIT ?
    """

    try:
        df = pd.read_sql_query(query, conn, params=params)
        if df.empty:
            st.info(t("flux_no_logs"))
            return

        level_colors = {
            "DEBUG": "#6c757d", "INFO": "#0dcaf0",
            "WARNING": "#ffc107", "ERROR": "#dc3545"
        }
        log_lines = []
        for _, row in df.iterrows():
            color = level_colors.get(row["level"], "#ffffff")
            log_lines.append(
                f'<span style="color:#6c757d">{row["timestamp"]}</span> '
                f'<span style="color:{color}">[{row["level"]}]</span> '
                f'<span style="color:#adb5bd">[{row["module"]}]</span> '
                f'{row["message"]}'
            )

        log_html = "<br>".join(log_lines)
        st.markdown(
            f'<div style="background:#1a1a2e;padding:12px;border-radius:8px;'
            f'font-family:monospace;font-size:12px;max-height:400px;overflow-y:auto;">'
            f'{log_html}</div>',
            unsafe_allow_html=True
        )
    except Exception as exc:
        st.error(t("flux_logs_error").format(exc=exc))
    finally:
        conn.close()


def render_alerts_config(settings: dict) -> dict | None:
    """Configuration des seuils d'alerte par flux."""
    st.markdown(f'<h4><i class="fas fa-bell" style="margin-right:7px;color:#7986cb;"></i>{t("flux_alerts_title")}</h4>', unsafe_allow_html=True)

    updated = dict(settings)
    changed = False

    col1, col2, col3 = st.columns(3)
    with col1:
        threshold = st.number_input(
            t("flux_alert_threshold"),
            min_value=0, max_value=100,
            value=settings.get("logging", {}).get("alert_score_threshold", 85),
            step=5,
            help=t("flux_alert_threshold_help")
        )
        if threshold != settings.get("logging", {}).get("alert_score_threshold", 85):
            updated.setdefault("logging", {})["alert_score_threshold"] = threshold
            changed = True

    with col2:
        tg_enabled = st.toggle(
            t("flux_telegram_enabled"),
            value=settings.get("logging", {}).get("telegram_enabled", False)
        )
        if tg_enabled != settings.get("logging", {}).get("telegram_enabled", False):
            updated.setdefault("logging", {})["telegram_enabled"] = tg_enabled
            changed = True

    with col3:
        dc_enabled = st.toggle(
            t("flux_discord_enabled"),
            value=settings.get("logging", {}).get("discord_enabled", False)
        )
        if dc_enabled != settings.get("logging", {}).get("discord_enabled", False):
            updated.setdefault("logging", {})["discord_enabled"] = dc_enabled
            changed = True

    return updated if changed else None


# ===========================================================
# PAGE PRINCIPALE
# ===========================================================

def render_flux_manager_page() -> None:
    """
    Page principale du Flux Manager.
    À appeler depuis streamlit_app.py dans un onglet Admin ou une page dédiée.
    """
    st.markdown(
        f'<h2 style="margin:0 0 4px;font-size:26px;font-weight:700;">'
        f'<i class="fas fa-shuffle" style="margin-right:12px;color:#7986cb;"></i>'
        f'{t("flux_title")}</h2>',
        unsafe_allow_html=True,
    )
    st.caption(t("flux_subtitle"))

    # Chargement des données
    settings = _get_settings()
    statuses = load_last_status_per_flux()
    stats = load_flux_stats(hours=24)

    # ---- Résumé global ----
    total = len(FLUX_DEFINITIONS)
    ok_count = sum(1 for s in statuses.values() if s.get("status") == "ok")
    err_count = sum(1 for s in statuses.values() if s.get("status") == "error")
    warn_count = total - ok_count - err_count

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(t("flux_total"), total)
    c2.metric(t("flux_operational"), ok_count)
    c3.metric(t("flux_in_error"), err_count,
              delta=f"+{err_count}" if err_count > 0 else None,
              delta_color="inverse")
    c4.metric(t("flux_unseen"), warn_count)

    # ---- Onglets ----
    tab_status, tab_pipeline, tab_controls, tab_charts, tab_logs, tab_alerts = st.tabs([
        "⬡ Status Board",
        "⊞ Pipeline",
        t("flux_tab_controls"),
        t("flux_tab_metrics"),
        "≡ Logs",
        t("flux_tab_alerts"),
    ])

    with tab_status:
        st.markdown(f'<h4><i class="fas fa-circle-check" style="margin-right:7px;color:#7986cb;"></i>{t("flux_status_realtime")}</h4>', unsafe_allow_html=True)
        hours = st.radio(t("flux_stats_window"), [1, 6, 24, 72],
                         index=2, format_func=lambda h: f"{h}h",
                         horizontal=True, key="status_hours")
        if st.button(t("flux_refresh"), use_container_width=False):
            st.rerun()
        render_status_board(statuses, stats, settings)

    with tab_pipeline:
        st.markdown(f'<h4><i class="fas fa-sitemap" style="margin-right:7px;color:#7986cb;"></i>{t("flux_pipeline_diagram")}</h4>', unsafe_allow_html=True)
        render_pipeline_diagram(statuses)
        st.caption(t("flux_legend"))

    with tab_controls:
        new_settings = render_controls(settings)
        if new_settings is not None:
            if _save_settings(new_settings):
                st.success(t("flux_saved"))
                time.sleep(0.5)
                st.rerun()

    with tab_charts:
        st.markdown(f'<h4><i class="fas fa-chart-bar" style="margin-right:7px;color:#7986cb;"></i>{t("flux_perf_metrics")}</h4>', unsafe_allow_html=True)
        selected_flux = st.radio(
            t("flux_to_analyze"),
            list(FLUX_DEFINITIONS.keys()),
            format_func=lambda k: FLUX_DEFINITIONS[k]["label"],
            horizontal=True, key="chart_flux"
        )
        hours_chart = st.radio(t("flux_period"), [1, 6, 24], index=1,
                               format_func=lambda h: f"{h}h",
                               horizontal=True, key="chart_hours")

        render_latency_chart(selected_flux, hours=hours_chart)

        # Summary table
        st.markdown(f'<h4><i class="fas fa-table" style="margin-right:7px;color:#7986cb;"></i>{t("flux_summary_24h")}</h4>', unsafe_allow_html=True)
        if stats:
            df_stats = pd.DataFrame(stats).T.reset_index()
            df_stats.columns = [
                t("flux_col_flux"), t("flux_col_calls"), t("flux_col_error_rate"),
                t("flux_col_avg_lat"), t("flux_col_p95_lat"), t("flux_col_items")
            ]
            df_stats[t("flux_col_flux")] = df_stats[t("flux_col_flux")].map(
                lambda k: FLUX_DEFINITIONS.get(k, {}).get("label", k)
            )
            st.table(df_stats)
        else:
            st.info(t("flux_no_stats"))

    with tab_logs:
        st.markdown(f'<h4><i class="fas fa-file-lines" style="margin-right:7px;color:#7986cb;"></i>{t("flux_logs_title")}</h4>', unsafe_allow_html=True)
        log_flux = st.radio(
            t("flux_filter_by"),
            ["Tous"] + list(FLUX_DEFINITIONS.keys()),
            format_func=lambda k: t("flux_all") if k == "Tous"
            else FLUX_DEFINITIONS[k]["label"],
            horizontal=True, key="log_flux"
        )
        n_logs = st.number_input(t("flux_nb_lines"), 10, 500, 50, step=10)

        render_flux_logs(
            flux_name=None if log_flux == "Tous" else log_flux,
            limit=n_logs
        )

    with tab_alerts:
        new_settings_alert = render_alerts_config(settings)
        if new_settings_alert is not None:
            if _save_settings(new_settings_alert):
                st.success(t("flux_alerts_saved"))
                st.rerun()


# ===========================================================
# DONNÉES DE DÉMO (pas de DB disponible)
# ===========================================================

def _generate_demo_status() -> dict[str, dict]:
    """Génère des statuts de démo pour l'affichage sans DB."""
    import random
    statuses = {}
    for flux_name in FLUX_DEFINITIONS:
        status = random.choices(
            ["ok", "ok", "ok", "error", "timeout"],
            weights=[70, 5, 5, 15, 5]
        )[0]
        statuses[flux_name] = {
            "status": status,
            "latency_ms": random.randint(100, 5000),
            "items_count": random.randint(1, 100),
            "timestamp": (datetime.utcnow() - timedelta(seconds=random.randint(0, 600))).isoformat(),
            "error_message": "Connection timeout (demo)" if status == "error" else None,
        }
    return statuses


def _generate_demo_metrics(flux_name: str | None, hours: int) -> pd.DataFrame:
    """Génère des métriques de démo."""
    import random
    import numpy as np

    rows = []
    n_points = hours * 12  # un point toutes les 5 min
    now = datetime.utcnow()
    fluxes = [flux_name] if flux_name else list(FLUX_DEFINITIONS.keys())

    for fx in fluxes:
        for i in range(n_points):
            ts = now - timedelta(minutes=i * 5)
            status = "error" if random.random() < 0.05 else "ok"
            rows.append({
                "timestamp": ts,
                "flux_name": fx,
                "status": status,
                "latency_ms": max(50, int(np.random.lognormal(6, 0.5))),
                "items_count": random.randint(1, 30),
                "error_message": "demo error" if status == "error" else None,
            })

    return pd.DataFrame(rows)


# ===========================================================
# ENTRY POINT (pour lancement direct)
# ===========================================================

if __name__ == "__main__":
    st.set_page_config(
        page_title="Flux Manager — Atlas Trader",
        page_icon="🔀",
        layout="wide",
        initial_sidebar_state="collapsed"
    )
    render_flux_manager_page()
