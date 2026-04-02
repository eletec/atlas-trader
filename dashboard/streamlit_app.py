"""
dashboard/streamlit_app.py — Dashboard principal Atlas Trader
Interface User (lecture seule) + Interface Admin (protégée par mot de passe).
"""
from __future__ import annotations

import hashlib
import threading
import time
from datetime import datetime
from queue import Queue, Empty


# Logo 34×34 extrait de atlas.ico (base64 PNG ~3KB — aucune dépendance fichier)
_LOGO_B64 = (
    "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"
)

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

try:
    from dashboard.flux_manager import render_flux_manager_page
except Exception:
    from flux_manager import render_flux_manager_page
from utils.i18n import t, set_lang, get_lang

# ===========================================================
# CONFIG PAGE
# ===========================================================

st.set_page_config(
    page_title="Atlas Trader",
    page_icon="images/atlas.ico",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def _get_theme() -> str:
    """Lit le thème depuis query params (dark par défaut)."""
    return st.query_params.get("theme", "dark")


def _inject_theme_css():
    """Injecte les overrides CSS selon le thème choisi."""
    theme = _get_theme()

    # Font Awesome 6 (icônes modernes unicouleur)
    st.markdown(
        '<link rel="stylesheet" '
        'href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css" '
        'crossorigin="anonymous">',
        unsafe_allow_html=True,
    )

    _LIGHT_CSS = """
        [data-testid="stApp"],
        [data-testid="stAppViewContainer"],
        [data-testid="stMainBlockContainer"],
        section.main { background-color: #f8f9fa !important; color: #31333F !important; }
        [data-testid="stHeader"] { background-color: #e9ecef !important; }
        [data-testid="stSidebar"] { background-color: #e9ecef !important; }
        p, h1, h2, h3, h4, label, span, div { color: #31333F; }
        [data-testid="metric-container"] {
            background-color: #ffffff !important;
            border: 1px solid #dee2e6 !important;
            border-radius: 8px; padding: 12px;
        }
        .stButton > button {
            background-color: #ffffff !important;
            color: #31333F !important;
            border: 1px solid #ced4da !important;
        }
        .stButton > button[kind="primary"] {
            background-color: #ff4b4b !important;
            color: #ffffff !important;
            border: none !important;
        }
        [data-testid="stSelectbox"] > div,
        [data-testid="stTextInput"] > div { background-color: #ffffff !important; }
        [data-testid="stDataFrame"], .stDataFrame { background-color: #ffffff !important; }
        [data-testid="stDataFrame"] * { color: #31333F !important; }
        [data-testid="stDataFrameResizable"] { background-color: #ffffff !important; }
        [data-testid="stAlert"] { background-color: #e8f4fd !important; }
        hr { border-color: #dee2e6 !important; }
        code, pre { background-color: #f1f3f5 !important; color: #31333F !important; }
    """

    _DARK_CSS = """
        [data-testid="stApp"],
        [data-testid="stAppViewContainer"],
        [data-testid="stMainBlockContainer"],
        section.main { background-color: #0e1117 !important; color: #FAFAFA !important; }
        [data-testid="stHeader"] { background-color: #0e1117 !important; }
        [data-testid="stSidebar"] { background-color: #161b22 !important; }
        p, h1, h2, h3, h4, label { color: #FAFAFA !important; }
        [data-testid="metric-container"] {
            background-color: #161b22 !important;
            border: 1px solid rgba(255,255,255,0.1) !important;
            border-radius: 8px; padding: 12px;
        }
        .stButton > button,
        .stButton button,
        button[data-testid^="stBaseButton"],
        [data-testid="stFormSubmitButton"] button {
            background-color: #21262d !important;
            color: #FAFAFA !important;
            border: 1px solid rgba(255,255,255,0.15) !important;
        }
        button[data-testid="stBaseButton-primary"],
        [data-testid="stFormSubmitButton"] button[kind="primary"] {
            background-color: #ff4b4b !important;
            color: #ffffff !important;
            border: none !important;
        }
        [data-baseweb="input"],
        [data-baseweb="select"] > div,
        [data-testid="stTextInput"] input,
        [data-testid="stNumberInput"] input {
            background-color: #161b22 !important;
            color: #FAFAFA !important;
            border-color: rgba(255,255,255,0.15) !important;
        }
        [data-testid="stDataFrame"], .stDataFrame { background-color: #161b22 !important; }
        [data-testid="stDataFrame"] * { color: #FAFAFA !important; }
        [data-testid="stDataFrameResizable"] { background-color: #161b22 !important; }
        [data-testid="stDataFrame"] iframe { filter: invert(0) !important; }
        [data-testid="stAlert"] { background-color: #1c2128 !important; }
        hr { border-color: rgba(255,255,255,0.1) !important; }
        code, pre { background-color: #161b22 !important; color: #FAFAFA !important; }
        /* Textarea (listes RSS, Nitter, Reddit…) */
        textarea, [data-baseweb="textarea"] textarea {
            background-color: #161b22 !important;
            color: #FAFAFA !important;
            border-color: rgba(255,255,255,0.15) !important;
        }
        /* Icône œil (champ password) et boutons internes des inputs */
        [data-testid="stTextInput"] button,
        [data-testid="stPasswordInput"] button,
        [data-baseweb="input"] button {
            background-color: transparent !important;
            color: #FAFAFA !important;
            border: none !important;
            box-shadow: none !important;
        }
        /* Selectbox : fond du contrôle */
        [data-baseweb="select"] > div:first-child {
            background-color: #21262d !important;
            border-color: rgba(255,255,255,0.15) !important;
        }
        [data-baseweb="select"] span,
        [data-baseweb="select"] div { color: #FAFAFA !important; }
        /* Selectbox : menu déroulant */
        [data-baseweb="popover"],
        ul[data-baseweb="menu"] {
            background-color: #21262d !important;
            border-color: rgba(255,255,255,0.15) !important;
        }
        ul[data-baseweb="menu"] li,
        [data-baseweb="option"] {
            background-color: #21262d !important;
            color: #FAFAFA !important;
        }
        ul[data-baseweb="menu"] li:hover,
        [data-baseweb="option"]:hover {
            background-color: #30363d !important;
        }
        /* Slider labels */
        [data-testid="stSlider"] span { color: #FAFAFA !important; }
        /* Number input arrows */
        [data-testid="stNumberInput"] button {
            background-color: #21262d !important;
            color: #FAFAFA !important;
            border-color: rgba(255,255,255,0.15) !important;
        }
        /* Form container (login + admin forms) */
        [data-testid="stForm"] {
            background-color: #161b22 !important;
            border: 1px solid rgba(255,255,255,0.1) !important;
            border-radius: 10px !important;
        }
        /* Tous les input internes (texte, password) */
        input, input[type="text"], input[type="password"] {
            background-color: #21262d !important;
            color: #FAFAFA !important;
            border-color: rgba(255,255,255,0.2) !important;
        }
        /* Icône œil (visibilité mot de passe) + boutons internes */
        [data-testid="stTextInput"] button svg,
        [data-testid="stPasswordInput"] button svg,
        [data-baseweb="input"] button svg {
            fill: #FAFAFA !important;
        }
        [data-testid="stTextInput"] button,
        [data-testid="stPasswordInput"] button,
        [data-baseweb="input"] button {
            background-color: #21262d !important;
            color: #FAFAFA !important;
            border: none !important;
        }
        /* Tab navigation */
        [data-testid="stTabs"] [data-baseweb="tab-list"] {
            background-color: #0e1117 !important;
        }
        [data-testid="stTabs"] button[role="tab"] {
            color: rgba(255,255,255,0.6) !important;
            background-color: transparent !important;
        }
        [data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
            color: #FAFAFA !important;
            border-bottom-color: #ff4b4b !important;
        }
    """


    if theme == "light":
        st.markdown(f"<style>{_LIGHT_CSS}</style>", unsafe_allow_html=True)
    elif theme == "dark":
        st.markdown(f"<style>{_DARK_CSS}</style>", unsafe_allow_html=True)
    elif theme == "system":
        st.markdown(f"""
        <style>
        @media (prefers-color-scheme: light) {{ {_LIGHT_CSS} }}
        @media (prefers-color-scheme: dark)  {{ {_DARK_CSS}  }}
        </style>
        """, unsafe_allow_html=True)

    # CSS global pour les tooltips Streamlit (rendus dans body via portal React)
    if theme != "light":
        st.markdown("""
<style id="atlas-tooltip-global">
/* Conteneur racine du tooltip — une seule bordure ici */
div[data-radix-popper-content-wrapper] {
    background-color: #21262d !important;
    color: #e6edf3 !important;
    border: 1px solid rgba(255,255,255,0.18) !important;
    border-radius: 6px !important;
    box-shadow: 0 4px 16px rgba(0,0,0,0.55) !important;
    padding: 7px 11px !important;
    font-size: 12px !important;
    line-height: 1.5 !important;
}
/* Tous les enfants : pas de bordure ni background propre */
div[data-radix-popper-content-wrapper] *,
[role="tooltip"],
[role="tooltip"] * {
    border: none !important;
    background: transparent !important;
    box-shadow: none !important;
    color: #e6edf3 !important;
    padding: 0 !important;
    margin: 0 !important;
}
</style>
""", unsafe_allow_html=True)

# ===========================================================
# SESSION STATE
# ===========================================================

def _init_session():
    defaults = {
        "admin_authenticated": False,
        "show_admin": False,
        "last_refresh": time.time(),
        "log_queue": Queue(maxsize=200),
        "force_run": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ===========================================================
# CHARGEMENT DES DONNÉES
# ===========================================================

@st.cache_data(ttl=30)
def _get_recent_decisions(n: int = 50) -> list[dict]:
    try:
        from storage.database import get_recent_decisions
        return get_recent_decisions(n)
    except Exception:
        return []


@st.cache_data(ttl=30)
def _get_recent_trades(n: int = 200) -> list[dict]:
    """Retourne uniquement les trades BUY/SELL (pas les HOLD)."""
    try:
        from storage.database import get_recent_decisions
        decisions = get_recent_decisions(2000)
        return [d for d in decisions if d.get("action") in ("BUY", "SELL")][:n]
    except Exception:
        return []


@st.cache_data(ttl=15)
def _get_portfolio() -> dict:
    try:
        from execution.paper_trader import PaperTrader
        return PaperTrader().get_portfolio()
    except Exception:
        return {"capital": 10000, "current_value": 10000, "total_pnl": 0,
                "total_pnl_pct": 0, "n_trades": 0}


@st.cache_data(ttl=30)
def _get_pnl_history() -> list[dict]:
    try:
        from storage.database import get_pnl_history
        return get_pnl_history()
    except Exception:
        return []


def _get_last_cycle() -> dict | None:
    decisions = _get_recent_decisions(1)
    return decisions[0] if decisions else None


def _get_settings() -> dict:
    try:
        from utils.config import load_settings
        from pathlib import Path
        _cfg_path = Path(__file__).parent.parent / "config" / "settings.yaml"
        return load_settings(_cfg_path)
    except Exception as _e:
        import logging
        logging.getLogger("zeitgeist.dashboard").error(f"load_settings failed: {_e}")
        st.session_state["_settings_error"] = str(_e)
        return {}


def _save_settings(settings: dict) -> bool:
    try:
        from utils.config import save_settings
        from pathlib import Path
        _cfg_path = Path(__file__).parent.parent / "config" / "settings.yaml"
        save_settings(settings, _cfg_path)
        return True
    except Exception:
        return False


# ===========================================================
# COMPOSANTS UI USER
# ===========================================================

def _run_cycle_with_trace(asset: str) -> dict:
    """
    Exécute un cycle complet noeud par noeud en affichant
    une trace en temps réel via st.status().
    Retourne le state final (même interface que run_cycle()).
    """
    import time
    from graph.workflow import (
        create_initial_state,
        node_fetch_news, node_crawl_web, node_run_mirofish,
        node_fetch_market_data, node_analyze_agents, node_synthesize,
        node_calculate_score, node_decide, node_execute,
        should_continue_after_news, should_execute,
    )

    STEPS = [
        ("fetch_news",      "News rapides (RSS / NewsAPI)",        node_fetch_news),
        ("crawl_web",       "Crawl web thématique",                node_crawl_web),
        ("run_mirofish",    "Simulation MiroFish (swarm)",         node_run_mirofish),
        ("fetch_market",    "Données marché (OHLCV / orderbook)",  node_fetch_market_data),
        ("agents",          "Analyse agents (fundamental, X…)",    node_analyze_agents),
        ("synthesize",      "Synthèse LLM finale",                 node_synthesize),
        ("score",           "Calcul du score global",              node_calculate_score),
        ("decide",          "Décision (BUY / SELL / HOLD)",        node_decide),
    ]

    state = create_initial_state(asset)
    t_total = time.time()

    with st.status("Cycle en cours…", expanded=True) as status:
        for key, label, fn in STEPS:
            status.write(f"⏳ **{label}**")
            t0 = time.time()
            try:
                patch = fn(state)
                if patch:
                    state.update(patch)
                elapsed = int((time.time() - t0) * 1000)

                # Arrêt conditionnel après fetch_news
                if key == "fetch_news":
                    if should_continue_after_news(state) == "abort":
                        status.write(f"⚠️ Aucune news — cycle interrompu")
                        break

                # Info contextuelle par étape
                if key == "fetch_news":
                    n = len(state.get("news_items", []))
                    status.write(f"✅ **{label}** — {n} news ({elapsed}ms)")
                elif key == "crawl_web":
                    s = state.get("crawler_status", "?")
                    status.write(f"✅ **{label}** — statut: {s} ({elapsed}ms)")
                elif key == "run_mirofish":
                    mf = state.get("mirofish_result") or {}
                    sig = mf.get("signal", "?")
                    conf = mf.get("confidence", 0)
                    status.write(f"✅ **{label}** — signal: {sig} conf: {conf:.0%} ({elapsed}ms)")
                elif key == "fetch_market":
                    mi = state.get("market_indicators") or {}
                    price = mi.get("price", 0)
                    rsi = mi.get("rsi_14", 0)
                    status.write(f"✅ **{label}** — BTC: ${price:,.0f} RSI: {rsi:.1f} ({elapsed}ms)")
                elif key == "agents":
                    n = len(state.get("agent_analyses", {}))
                    errs = len(state.get("errors", []))
                    status.write(f"✅ **{label}** — {n} agents, {errs} erreurs ({elapsed}ms)")
                elif key == "synthesize":
                    status.write(f"✅ **{label}** — tokens: {state.get('llm_tokens_used', 0)} ({elapsed}ms)")
                elif key == "score":
                    sc = state.get("global_score", 0)
                    status.write(f"✅ **{label}** — score: {sc:.1f}/100 ({elapsed}ms)")
                elif key == "decide":
                    dec = (state.get("decision") or {})
                    action = dec.get("action", "HOLD")
                    status.write(f"✅ **{label}** — **{action}** ({elapsed}ms)")
                    # Exécution conditionnelle
                    if should_execute(state) == "execute":
                        status.write(f"⏳ **Exécution du trade ({action})**")
                        t0e = time.time()
                        try:
                            patch = node_execute(state)
                            if patch:
                                state.update(patch)
                            elapsed_e = int((time.time() - t0e) * 1000)
                            tr = state.get("trade_result") or {}
                            status.write(f"✅ **Trade exécuté** — {tr.get('status','?')} ({elapsed_e}ms)")
                        except Exception as exc:
                            status.write(f"❌ **Exécution échouée** — {exc}")
            except Exception as exc:
                elapsed = int((time.time() - t0) * 1000)
                status.write(f"❌ **{label}** — {exc} ({elapsed}ms)")
                state.setdefault("errors", []).append(f"{key}: {exc}")

        total_ms = int((time.time() - t_total) * 1000)
        errs = state.get("errors", [])
        final_action = (state.get("decision") or {}).get("action", "N/A")
        final_score  = state.get("global_score", 0)
        if errs:
            status.update(
                label=f"Cycle terminé avec {len(errs)} erreur(s) — {final_action} | score {final_score:.0f} | {total_ms}ms",
                state="error", expanded=False,
            )
        else:
            status.update(
                label=f"Cycle terminé — {final_action} | score {final_score:.0f} | {total_ms}ms",
                state="complete", expanded=False,
            )

    state["cycle_duration_ms"] = total_ms
    return state


def render_header():
    """
    Barre nav position:fixed + menu hamburger URL-based (100% <a href>, pas de JS).
    Logo Atlas en base64. Hamburger via ?menu=1/0 query param.
    """
    theme      = _get_theme()
    lang_param = st.query_params.get("lang",  "fr")
    show_admin = st.query_params.get("admin", "0") == "1"
    menu_open  = st.query_params.get("menu",  "0") == "1"
    _action    = st.query_params.get("_action", "")

    set_lang(lang_param)
    st.session_state["show_admin"] = show_admin

    # ─ Actions ─────────────────────────────────────────────────────────────
    if _action == "logout":
        st.query_params.pop("_action", None)
        try:
            from dashboard.auth import logout as _logout
            import extra_streamlit_components as _stx
            _cm = _stx.CookieManager(key="atlas_cm")
            _logout(_cm)
        except Exception:
            pass
        st.query_params.clear()
        st.rerun()

    if _action == "refresh":
        st.query_params.pop("_action", None)
        st.cache_data.clear()
        st.rerun()

    if _action == "force_run":
        st.query_params.pop("_action", None)
        try:
            cfg   = _get_settings()
            asset = cfg.get("project", {}).get("asset", "BTC/USDT")
            state = _run_cycle_with_trace(asset)
            st.cache_data.clear()
            decision = state.get("decision") or {}
            st.toast(
                f"\u26a1 Score\u00a0: {state.get('global_score', 0):.0f}"
                f" | {decision.get('action', 'N/A')}",
                icon="\u2705",
            )
            st.rerun()
        except Exception as exc:
            st.toast(f"Erreur Force Run\u00a0: {exc}", icon="\U0001f6a8")

    # ─ URLs ─────────────────────────────────────────────────────────────────
    adm   = "1" if show_admin else "0"
    # _sid propagé dans toutes les URLs pour que la session survive aux rechargements
    _sid  = st.session_state.get("_session_id", "")
    _sid_param = f"&_sid={_sid}" if _sid else ""
    m_open  = f"lang={lang_param}&theme={theme}&admin={adm}&menu=1{_sid_param}"
    m_close = f"lang={lang_param}&theme={theme}&admin={adm}&menu=0{_sid_param}"
    base    = f"lang={lang_param}&theme={theme}&admin={adm}&menu=0{_sid_param}"
    u_refresh  = f"?_action=refresh&{base}"
    u_force    = f"?_action=force_run&{base}"
    u_hamburger = f"?{m_close if menu_open else m_open}"
    # menu items (chaque clic ferme le menu)
    u_admin    = f"?lang={lang_param}&theme={theme}&admin=1&menu=0{_sid_param}"
    u_logout   = f"?_action=logout&{base}"
    u_t_light  = f"?lang={lang_param}&theme=light&admin={adm}&menu=0{_sid_param}"
    u_t_dark   = f"?lang={lang_param}&theme=dark&admin={adm}&menu=0{_sid_param}"
    u_t_system = f"?lang={lang_param}&theme=system&admin={adm}&menu=0{_sid_param}"
    u_l_fr     = f"?lang=fr&theme={theme}&admin={adm}&menu=0{_sid_param}"
    u_l_en     = f"?lang=en&theme={theme}&admin={adm}&menu=0{_sid_param}"

    # ─ CSS variables ────────────────────────────────────────────────────────
    if theme == "light":
        nav_bg  = "#f8f9fa"; nav_fg = "#31333F"
        nav_bdr = "#dee2e6"; dd_bg  = "#ffffff"; dd_sep = "#dee2e6"
    elif theme == "system":
        # Sera surcharg\u00e9 par _inject_theme_css via @media
        nav_bg  = "#0e1117"; nav_fg = "#FAFAFA"
        nav_bdr = "rgba(128,128,128,0.3)"; dd_bg = "#1e2128"; dd_sep = "rgba(255,255,255,0.1)"
    else:
        nav_bg  = "#0e1117"; nav_fg = "#FAFAFA"
        nav_bdr = "rgba(128,128,128,0.3)"; dd_bg = "#1e2128"; dd_sep = "rgba(255,255,255,0.1)"

    # ─ Styles helper ────────────────────────────────────────────────────────
    S_BTN = (f"text-decoration:none;border-radius:5px;padding:5px 11px;"
             f"font-size:14px;color:{nav_fg};white-space:nowrap;"
             f"background:rgba(128,128,128,0.13);")
    S_HBG_ON  = (f"text-decoration:none;border-radius:5px;padding:5px 10px;"
                 f"font-size:18px;line-height:1;color:{nav_fg};"
                 f"background:rgba(255,75,75,0.25);")
    S_HBG_OFF = (f"text-decoration:none;border-radius:5px;padding:5px 10px;"
                 f"font-size:18px;line-height:1;color:{nav_fg};"
                 f"background:rgba(128,128,128,0.13);")
    S_HBG = S_HBG_ON if menu_open else S_HBG_OFF
    S_SEP = f"height:1px;background:{dd_sep};margin:5px 0;"
    S_LBL = (f"padding:5px 14px 2px;font-size:10px;opacity:0.55;"
             f"color:{nav_fg};text-transform:uppercase;letter-spacing:.08em;")
    S_ROW = "display:flex;gap:6px;padding:4px 14px 8px;flex-wrap:wrap;"

    def pill(url, label, active):
        bg = "rgba(255,75,75,0.4)" if active else "rgba(128,128,128,0.13)"
        fw = "700" if active else "400"
        return (f'<a href="{url}" target="_self" style="text-decoration:none;border-radius:6px;' +
                f'padding:4px 11px;font-size:13px;color:{nav_fg};' +
                f'white-space:nowrap;background:{bg};font-weight:{fw};">{label}</a>')

    admin_icon  = '<i class="fas fa-lock-open" style="font-size:13px;"></i>' if st.session_state.get("admin_authenticated") else '<i class="fas fa-gear" style="font-size:13px;"></i>'
    admin_label = f"{admin_icon}&nbsp; Administration"
    admin_bg    = f"background:rgba(255,75,75,0.18);" if show_admin else ""

    # ─ Dropdown HTML (rendu seulement si menu_open) ─────────────────────────
    dropdown_html = ""
    if menu_open:
        dropdown_html = f"""
<div style="position:fixed;top:49px;right:8px;min-width:235px;
            z-index:9998;background:{dd_bg};
            border:1px solid {nav_bdr};border-radius:10px;
            box-shadow:0 6px 30px rgba(0,0,0,0.35);
            padding:6px 0;display:flex;flex-direction:column;">
  <a href="{u_admin}" style="text-decoration:none;display:block;padding:10px 16px;
     font-size:14px;color:{nav_fg};{admin_bg}" target="_blank">{admin_label}</a>
  <div style="{S_SEP}"></div>
  <div style="{S_LBL}"><i class="fas fa-palette" style="margin-right:5px;"></i>Thème</div>
  <div style="{S_ROW}">
    {pill(u_t_light,  '<i class="fas fa-sun"></i> Clair',    theme == "light")}
    {pill(u_t_dark,   '<i class="fas fa-moon"></i> Sombre',   theme == "dark")}
    {pill(u_t_system, '<i class="fas fa-desktop"></i> Système', theme == "system")}
  </div>
  <div style="{S_SEP}"></div>
  <div style="{S_LBL}"><i class="fas fa-globe" style="margin-right:5px;"></i>Langue</div>
  <div style="{S_ROW}">
    {pill(u_l_fr, '<i class="fas fa-flag" style="font-size:11px;"></i> FR', lang_param == "fr")}
    {pill(u_l_en, '<i class="fas fa-flag" style="font-size:11px;"></i> EN', lang_param == "en")}
  </div>
{f'''  <div style="{S_SEP}"></div>
  <a href="{u_logout}" style="text-decoration:none;display:block;padding:10px 16px;
     font-size:14px;color:{nav_fg};" target="_self">
    <i class="fas fa-right-from-bracket" style="margin-right:8px;opacity:0.7;"></i>
    {t("logout_btn")} &mdash; {st.session_state.get("username", "")}
  </a>''' if st.session_state.get('admin_authenticated') else ''}
</div>"""

    # ─ Rendu final ──────────────────────────────────────────────────────────
    st.markdown(f"""
<style>
header[data-testid="stHeader"]{{display:none!important;}}
.main .block-container,[data-testid="stMainBlockContainer"]{{padding-top:56px!important;padding-bottom:0!important;}}
[data-testid="stTabs"]{{margin-top:-1rem!important;}}
[data-testid="stMainBlockContainer"] > div:first-child {{gap:0!important;}}
</style>
<nav style="position:fixed;top:0;left:0;right:0;height:48px;
            background:{nav_bg};z-index:9999;
            border-bottom:1px solid {nav_bdr};
            box-shadow:0 2px 10px rgba(0,0,0,0.24);
            display:flex;align-items:center;
            padding:0 1rem;gap:10px;box-sizing:border-box;">
  <a href="?lang={lang_param}&theme={theme}&admin=0&menu=0{_sid_param}" target="_self"
     style="display:flex;align-items:center;flex-shrink:0;text-decoration:none;">
    <img src="data:image/png;base64,{_LOGO_B64}"
         style="height:32px;width:32px;border-radius:7px;object-fit:cover;"
         alt="Atlas">
  </a>
  <span style="flex:1;color:{nav_fg};font-weight:700;font-size:15px;
               white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
    Atlas Trader
    <span style="font-weight:400;font-size:12px;opacity:0.5;"> &middot; Paper Trading BTC/USDT</span>
  </span>
  <span style="font-size:12px;color:{nav_fg};opacity:0.6;white-space:nowrap;flex-shrink:0;font-variant-numeric:tabular-nums;">{datetime.now().strftime('%d/%m/%Y %H:%M')}</span>
  <a href="{u_refresh}" style="{S_BTN}" title="Rafra\u00eechir" target="_self"><i class="fas fa-rotate-right"></i></a>
  <a href="{u_force}"   style="{S_BTN}" title="Force Run" target="_self"><i class="fas fa-bolt"></i></a>
  <a href="{u_hamburger}" style="{S_HBG}" title="Menu" target="_self"><i class="fas fa-bars"></i></a>
</nav>
{dropdown_html}
""", unsafe_allow_html=True)


def _card_colors(theme: str) -> tuple[str, str, str, str, str]:
    """(bg, border, text, muted, icon_color) selon le thème courant."""
    if theme == "light":
        return "#ffffff", "#dee2e6", "#212529", "#6c757d", "#5c73c0"
    return "#1b1f27", "rgba(255,255,255,0.1)", "#f0f0f0", "rgba(255,255,255,0.45)", "#7986cb"


def _html_card(fa: str, label: str, val_html: str,
               bg: str, bdr: str, txt: str, muted: str, ic: str,
               delta: str | None = None, d_pos: bool | None = None) -> str:
    """Génère une carte Bootstrap-like en HTML pur avec icône Font Awesome."""
    d_html = ""
    if delta:
        dc  = "#2ecc71" if d_pos is True else "#e74c3c" if d_pos is False else muted
        arr = "▲ " if d_pos is True else "▼ " if d_pos is False else ""
        d_html = (f'<div style="font-size:11px;color:{dc};margin-top:3px;">' +
                  arr + delta + '</div>')
    return (
        f'<div style="background:{bg};border:1px solid {bdr};border-radius:12px;' +
        f'padding:16px 14px 13px;min-width:0;box-sizing:border-box;">' +
        f'<div style="font-size:22px;color:{ic};margin-bottom:8px;">' +
        f'<i class="{fa}"></i></div>' +
        f'<div style="font-size:22px;font-weight:700;color:{txt};line-height:1.1;">' +
        val_html + '</div>' +
        f'<div style="font-size:11px;color:{muted};text-transform:uppercase;' +
        f'letter-spacing:.05em;margin-top:5px;">{label}</div>' +
        d_html + '</div>'
    )


def render_climate_metrics(last_cycle: dict | None):
    """Indicateurs de marché en cartes Bootstrap-like avec Font Awesome."""
    theme  = _get_theme()
    score  = last_cycle.get("score",  50) if last_cycle else 50
    action = last_cycle.get("action", "—") if last_cycle else "—"
    ts     = last_cycle.get("timestamp", "") if last_cycle else ""

    time_ago = "—"
    if ts:
        try:
            diff = int((datetime.utcnow() - datetime.fromisoformat(ts)).total_seconds() / 60)
            time_ago = f"{diff} min" if diff < 60 else f"{diff // 60} h"
        except Exception:
            pass

    act_map = {
        "BUY":  ("#2ecc71", "fas fa-arrow-trend-up"),
        "SELL": ("#e74c3c", "fas fa-arrow-trend-down"),
        "HOLD": ("#f39c12", "fas fa-hand"),
    }
    act_color, act_fa = act_map.get(action, ("#aaa", "fas fa-minus"))

    above_ma50 = (last_cycle or {}).get("above_ma50", None)
    ma_50      = (last_cycle or {}).get("ma_50", 0)
    if above_ma50 is True:
        ma50_val, ma50_col = t("ma50_bull"), "#2ecc71"
        ma50_delta, ma50_d_pos = (f"MA50 ${ma_50:,.0f}" if ma_50 else None), True
    elif above_ma50 is False:
        ma50_val, ma50_col = t("ma50_bear"), "#e74c3c"
        ma50_delta, ma50_d_pos = (
            f"MA50 ${ma_50:,.0f} — {t('buy_blocked')}" if ma_50 else t("buy_blocked"),
            False,
        )
    else:
        ma50_val, ma50_col, ma50_delta, ma50_d_pos = "N/A", "#888", None, None

    score_delta = f"{score - 50:+.0f} pts" if last_cycle else None
    score_d_pos = bool(score > 50) if last_cycle else None
    pct         = min(max(score, 0), 100)
    bar_col     = "#2ecc71" if score >= 60 else "#f39c12" if score >= 40 else "#e74c3c"
    score_bar   = (
        f'<div style="height:3px;background:rgba(128,128,128,.2);border-radius:2px;margin-top:6px;">' +
        f'<div style="height:3px;width:{pct}%;background:{bar_col};border-radius:2px;"></div></div>'
    )

    bg, bdr, txt, muted, ic = _card_colors(theme)
    kw = dict(bg=bg, bdr=bdr, txt=txt, muted=muted, ic=ic)

    grid = (
        _html_card("fas fa-bullseye", t("score_label"),
                   f'{score:.0f}<span style="font-size:14px;font-weight:400;opacity:.5;">/100</span>' + score_bar,
                   delta=score_delta, d_pos=score_d_pos, **kw) +
        _html_card(act_fa, t("last_decision_label"),
                   f'<span style="color:{act_color}">{action}</span>',
                   **kw) +
        _html_card("fas fa-clock-rotate-left", t("last_cycle_label"), time_ago, **kw) +
        _html_card("fas fa-chart-line", t("ma50_label"),
                   f'<span style="color:{ma50_col}">{ma50_val}</span>',
                   delta=ma50_delta, d_pos=ma50_d_pos, **kw)
    )

    st.markdown(
        f'<h3 style="margin:0 0 10px;font-size:18px;">' +
        f'<i class="fas fa-gauge-high" style="margin-right:8px;color:#7986cb;"></i>' +
        f'{t("climate_title")}</h3>' +
        f'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));' +
        f'gap:12px;margin-bottom:8px;">{grid}</div>',
        unsafe_allow_html=True,
    )


def render_portfolio(portfolio: dict):
    """Portefeuille paper en cartes Bootstrap-like avec Font Awesome."""
    theme   = _get_theme()
    pnl     = portfolio.get("total_pnl", 0)
    pnl_pct = portfolio.get("total_pnl_pct", 0)
    pnl_pos = pnl >= 0
    pnl_col = "#2ecc71" if pnl_pos else "#e74c3c"

    bg, bdr, txt, muted, ic = _card_colors(theme)
    kw = dict(bg=bg, bdr=bdr, txt=txt, muted=muted, ic=ic)

    grid = (
        _html_card("fas fa-wallet", t("capital_label"),
                   f'${portfolio.get("capital", 10000):,.0f}', **kw) +
        _html_card("fas fa-coins", t("value_label"),
                   f'${portfolio.get("current_value", 10000):,.0f}', **kw) +
        _html_card("fas fa-arrow-trend-up", t("pnl_label"),
                   f'<span style="color:{pnl_col}">${pnl:+,.2f}</span>',
                   delta=f"{pnl_pct:+.2f}%", d_pos=pnl_pos, **kw) +
        _html_card("fas fa-right-left", t("trades_label"),
                   str(portfolio.get("n_trades", 0)), **kw)
    )

    st.markdown(
        f'<h3 style="margin:0 0 10px;font-size:18px;">' +
        f'<i class="fas fa-briefcase" style="margin-right:8px;color:#7986cb;"></i>' +
        f'{t("portfolio_title")}</h3>' +
        f'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));' +
        f'gap:12px;margin-bottom:16px;">{grid}</div>',
        unsafe_allow_html=True,
    )


def render_pnl_chart(history: list[dict]):
    """Graphique de performance cumulée."""
    st.markdown(f'<h3 style="margin:0 0 12px;font-size:18px;"><i class="fas fa-chart-area" style="margin-right:8px;color:#7986cb;"></i>{t("perf_chart_title")}</h3>', unsafe_allow_html=True)

    if not history:
        st.info(t("no_perf_data"))
        return

    df = pd.DataFrame(history)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["cumulative_pnl"] = df["result_24h"].fillna(0).cumsum()
    final_pnl = df["cumulative_pnl"].iloc[-1]
    color = "#2ecc71" if final_pnl >= 0 else "#e74c3c"

    fig = go.Figure()
    # Courbe P&L
    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=df["cumulative_pnl"],
        fill="tozeroy",
        fillcolor=f"rgba({'0,200,100' if final_pnl >= 0 else '200,50,50'}, 0.15)",
        line=dict(color=color, width=2),
        name="P&L cumulé ($)",
        yaxis="y1"
    ))
    # Prix BTC en overlay si disponible
    if "entry_price" in df.columns and df["entry_price"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["entry_price"],
            line=dict(color="#f39c12", width=1, dash="dot"),
            name="Prix BTC ($)",
            yaxis="y2", opacity=0.6
        ))
    # Marqueurs BUY/SELL
    if "action" in df.columns:
        buys = df[df["action"] == "BUY"]
        sells = df[df["action"] == "SELL"]
        if not buys.empty:
            fig.add_trace(go.Scatter(
                x=buys["timestamp"], y=buys["cumulative_pnl"],
                mode="markers", marker=dict(symbol="triangle-up", size=10, color="#2ecc71"),
                name="BUY", yaxis="y1"
            ))
        if not sells.empty:
            fig.add_trace(go.Scatter(
                x=sells["timestamp"], y=sells["cumulative_pnl"],
                mode="markers", marker=dict(symbol="triangle-down", size=10, color="#e74c3c"),
                name="SELL", yaxis="y1"
            ))
    fig.update_layout(
        height=320, margin=dict(l=0, r=0, t=20, b=0),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(gridcolor="rgba(128,128,128,0.2)"),
        yaxis=dict(gridcolor="rgba(128,128,128,0.2)", tickprefix="$", title="P&L"),
        yaxis2=dict(overlaying="y", side="right", showgrid=False,
                    tickprefix="$", title="BTC", tickfont=dict(color="#f39c12")),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_btc_live_chart():
    """Graphique BTC prix en temps réel avec niveaux SL/TP des positions ouvertes."""
    st.markdown(f'<h3 style="margin:0 0 12px;font-size:18px;"><i class="fas fa-satellite-dish" style="margin-right:8px;color:#7986cb;"></i>{t("btc_live_title")}</h3>', unsafe_allow_html=True)

    try:
        from agents.market_data_agent import MarketDataAgent
        from storage.database import get_recent_decisions
        agent = MarketDataAgent()
        indicators = agent.get_indicators("BTC/USDT")
        current_price = indicators.get("price", 0)
        ma_50 = indicators.get("ma_50", 0)

        open_pos = [
            d for d in get_recent_decisions(500)
            if d.get("action") in ("BUY", "SELL") and d.get("result_24h") is None
        ]
    except Exception as exc:
        st.warning(f'{t("data_load_error")} : {exc}')
        return

    if not open_pos:
        c1, c2, c3 = st.columns(3)
        c1.metric(t("btc_price_label"), f"${current_price:,.2f}" if current_price else "—")
        if ma_50:
            c2.metric(t("ma50_short", None) if False else "MA50", f"${ma_50:,.2f}",
                      delta=f"{(current_price/ma_50-1)*100:+.1f}%" if current_price and ma_50 else None,
                      delta_color="normal")
        c3.metric(t("open_pos_label"), "0")

        # Graphique prix 24h même sans positions
        try:
            import ccxt
            exchange = ccxt.binance()
            ohlcv = exchange.fetch_ohlcv("BTC/USDT", timeframe="15m", limit=96)
            times  = [row[0] for row in ohlcv]
            closes = [row[4] for row in ohlcv]
            fig_empty = go.Figure()
            fig_empty.add_trace(go.Scatter(
                x=pd.to_datetime(times, unit="ms"),
                y=closes,
                mode="lines",
                line=dict(color="#00d4ff", width=2),
                name="BTC/USDT",
            ))
            if ma_50:
                fig_empty.add_hline(y=ma_50,
                    line=dict(color="#e74c3c" if current_price < ma_50 else "#2ecc71",
                              width=1, dash="dash"),
                    annotation_text=f"MA50 ${ma_50:,.0f}",
                    annotation_font=dict(size=11))
            fig_empty.update_layout(
                height=280, margin=dict(l=0, r=60, t=20, b=0),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                yaxis=dict(gridcolor="rgba(128,128,128,0.15)", tickprefix="$"),
                xaxis=dict(gridcolor="rgba(128,128,128,0.1)"),
                showlegend=False,
            )
            st.plotly_chart(fig_empty, use_container_width=True)
        except Exception:
            st.info(t("no_open_pos"))
        return

    fig = go.Figure()

    # Ligne prix actuel
    prices = [float(p["entry_price"]) for p in open_pos if p.get("entry_price")]
    all_levels = prices.copy()
    if ma_50: all_levels.append(ma_50)
    sls = [float(p["sl_price"]) for p in open_pos if p.get("sl_price")]
    tps = [float(p["tp_price"]) for p in open_pos if p.get("tp_price")]
    all_levels += sls + tps
    if not all_levels:
        all_levels = [current_price * 0.95, current_price * 1.05]
    y_min = min(all_levels) * 0.998
    y_max = max(all_levels) * 1.002

    # Ligne prix courant
    fig.add_hline(y=current_price, line=dict(color="#00d4ff", width=2),
                  annotation_text=f"  Prix actuel ${current_price:,.0f}",
                  annotation_font=dict(color="#00d4ff", size=12))

    # Ligne MA50
    if ma_50:
        color_ma = "#2ecc71" if current_price > ma_50 else "#e74c3c"
        fig.add_hline(y=ma_50, line=dict(color=color_ma, width=1, dash="dash"),
                      annotation_text=f"  MA50 ${ma_50:,.0f}",
                      annotation_font=dict(color=color_ma, size=11))

    # Niveaux SL/TP de chaque position
    for i, pos in enumerate(open_pos):
        entry = pos.get("entry_price", 0)
        sl = pos.get("sl_price", 0)
        tp = pos.get("tp_price", 0)
        ts = pos.get("timestamp", "")[:10]
        size = pos.get("position_size", 0)
        if not entry: continue
        pnl_float = (current_price - entry) / entry * size if entry else 0
        label = f"  #{i+1} {ts} ${size:,.0f} | P&L {pnl_float:+,.0f}$"
        fig.add_hline(y=entry, line=dict(color="#f39c12", width=1, dash="dot"),
                      annotation_text=label,
                      annotation_font=dict(color="#f39c12", size=10),
                      annotation_position="right")
        if sl:
            fig.add_hline(y=sl, line=dict(color="#e74c3c", width=1, dash="dot"),
                          annotation_text=f"  SL #{i+1}",
                          annotation_font=dict(color="#e74c3c", size=10),
                          annotation_position="left")
        if tp:
            fig.add_hline(y=tp, line=dict(color="#2ecc71", width=1, dash="dot"),
                          annotation_text=f"  TP #{i+1}",
                          annotation_font=dict(color="#2ecc71", size=10),
                          annotation_position="left")

    fig.update_layout(
        height=380, margin=dict(l=0, r=120, t=30, b=0),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        yaxis=dict(gridcolor="rgba(128,128,128,0.2)", tickprefix="$", range=[y_min, y_max]),
        xaxis=dict(visible=False),
        showlegend=False,
    )

    n_open = len(open_pos)
    c1, c2, c3 = st.columns(3)
    c1.metric(t("btc_price_label"), f"${current_price:,.2f}" if current_price else "—")
    if ma_50:
        c2.metric("MA50", f"${ma_50:,.2f}",
                  delta=f"{(current_price/ma_50-1)*100:+.1f}%" if current_price else None,
                  delta_color="normal")
    c3.metric(t("open_pos_label"), n_open)
    st.plotly_chart(fig, use_container_width=True)


def render_trades_list(trades: list[dict]):
    """Liste détaillée des trades exécutés."""
    st.markdown(f'<h3 style="margin:0 0 12px;font-size:18px;"><i class="fas fa-clock-rotate-left" style="margin-right:8px;color:#7986cb;"></i>{t("trades_title")}</h3>', unsafe_allow_html=True)
    if not trades:
        st.info(t("no_trades"))
        return

    theme = _get_theme()
    if theme == "light":
        tbl_bg   = "#ffffff"; tbl_fg   = "#212529"
        head_bg  = "#f1f3f5"; row_alt  = "#f8f9fa"
        border   = "#dee2e6"; sep      = "#e9ecef"
    else:
        tbl_bg   = "#161b22"; tbl_fg   = "#e6edf3"
        head_bg  = "#0d1117"; row_alt  = "#1b2129"
        border   = "rgba(255,255,255,0.08)"; sep = "rgba(255,255,255,0.05)"

    cols = [t("col_date"), t("col_action"), t("col_entry"), t("col_size"),
            "SL", "TP", t("col_pnl"), t("col_score")]

    header_cells = "".join(
        f'<th style="padding:9px 12px;font-size:12px;font-weight:600;'
        f'text-transform:uppercase;letter-spacing:.05em;color:{tbl_fg};'
        f'opacity:.65;background:{head_bg};white-space:nowrap;'
        f'border-bottom:2px solid {border};">{c}</th>'
        for c in cols
    )

    rows_html = ""
    for i, trade in enumerate(trades):
        pnl    = trade.get("result_24h")
        action = trade.get("action", "")
        bg     = row_alt if i % 2 == 1 else tbl_bg

        action_color = "#2ecc71" if action == "BUY" else ("#e74c3c" if action == "SELL" else tbl_fg)
        if pnl is None:
            pnl_str   = f'<span style="opacity:.45;">{t("pending")}</span>'
        elif pnl >= 0:
            pnl_str   = f'<span style="color:#2ecc71;font-weight:600;">${pnl:+,.2f}</span>'
        else:
            pnl_str   = f'<span style="color:#e74c3c;font-weight:600;">${pnl:+,.2f}</span>'

        cells = [
            trade.get("timestamp", "")[:16].replace("T", " "),
            f'<span style="color:{action_color};font-weight:600;">{action}</span>',
            f'${trade.get("entry_price", 0):,.2f}' if trade.get("entry_price") else "—",
            f'${trade.get("position_size", 0):,.0f}' if trade.get("position_size") else "—",
            f'${trade.get("sl_price", 0):,.2f}'    if trade.get("sl_price")    else "—",
            f'${trade.get("tp_price", 0):,.2f}'    if trade.get("tp_price")    else "—",
            pnl_str,
            f'{trade.get("score", 0):.0f}/100',
        ]
        td_style = (f'padding:8px 12px;font-size:13px;color:{tbl_fg};'
                    f'white-space:nowrap;border-bottom:1px solid {sep};')
        tds = "".join(f'<td style="{td_style}">{c}</td>' for c in cells)
        rows_html += f'<tr style="background:{bg};">{tds}</tr>'

    html = f"""
<div style="overflow-y:auto;max-height:520px;border:1px solid {border};
            border-radius:10px;background:{tbl_bg};">
  <table style="border-collapse:collapse;width:100%;min-width:700px;">
    <thead><tr>{header_cells}</tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>"""
    st.markdown(html, unsafe_allow_html=True)



def render_last_decision(last_cycle: dict | None):
    """Affiche la dernière décision avec explication IA."""
    st.markdown(f'<h3 style="margin:0 0 12px;font-size:18px;"><i class="fas fa-robot" style="margin-right:8px;color:#7986cb;"></i>{t("last_decision_title")}</h3>', unsafe_allow_html=True)

    if not last_cycle:
        st.info(t("no_cycle"))
        return

    action = last_cycle.get("action", "HOLD")
    action_color = {"BUY": "green", "SELL": "red", "HOLD": "orange"}.get(action, "gray")
    explanation = last_cycle.get("explanation", t("no_explanation"))

    # Formatage de la date/heure de la décision
    ts = last_cycle.get("timestamp", "")
    ts_label = ""
    if ts:
        try:
            dt = datetime.fromisoformat(ts)
            ts_label = dt.strftime("%d/%m/%Y à %H:%M")
        except Exception:
            ts_label = ts[:16]

    st.markdown(
        f"<div style='border-left:4px solid {action_color}; padding:12px; "
        f"border-radius:4px;'>"
        f"<strong style='color:{action_color}'>{action}</strong> — "
        f"Score : {last_cycle.get('score', 0):.0f}/100"
        + (f" &nbsp;<span style='font-size:11px;opacity:0.55;'>🕐 {ts_label}</span>" if ts_label else "")
        + f"<br><br>{explanation}</div>",
        unsafe_allow_html=True
    )


def render_live_logs():
    """Affiche les 50 derniers logs en temps réel."""
    st.markdown(f'<h3 style="margin:0 0 12px;font-size:18px;"><i class="fas fa-terminal" style="margin-right:8px;color:#7986cb;"></i>{t("logs_title")}</h3>', unsafe_allow_html=True)
    try:
        from storage.database import get_connection
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT timestamp, level, module, message FROM logs "
                "ORDER BY timestamp DESC LIMIT 50"
            ).fetchall()
        if rows:
            log_lines = []
            for row in rows:
                level_color = {
                    "DEBUG": "#6c757d", "INFO": "#0dcaf0",
                    "WARNING": "#ffc107", "ERROR": "#dc3545"
                }.get(row[1], "#fff")
                log_lines.append(
                    f'<span style="color:#6c757d">{row[0]}</span> '
                    f'<span style="color:{level_color}">[{row[1]}]</span> '
                    f'<span style="color:#adb5bd">[{row[2]}]</span> {row[3]}'
                )
            st.markdown(
                f'<div style="border:1px solid rgba(128,128,128,0.2);padding:12px;border-radius:8px;'
                f'font-family:monospace;font-size:11px;max-height:350px;'
                f'overflow-y:auto;">{"<br>".join(log_lines)}</div>',
                unsafe_allow_html=True
            )
        else:
            st.info(t("no_logs"))
    except Exception:
        st.info(t("logs_unavailable"))


def render_force_run_button():
    """Bouton pour forcer un cycle immédiatement."""
    if st.button("Force Run", type="primary", use_container_width=True,
                 help="Déclenche un cycle de trading immédiat"):
        with st.spinner("Cycle en cours..."):
            try:
                from graph.workflow import run_cycle
                cfg = _get_settings()
                asset = cfg.get("project", {}).get("asset", "BTC/USDT")
                state = run_cycle(asset=asset)
                st.cache_data.clear()
                decision = state.get("decision") or {}
                st.success(
                    f"Cycle terminé — "
                    f"Score: {state.get('global_score', 0):.0f} | "
                    f"Décision: {decision.get('action', 'N/A')}"
                )
                st.rerun()
            except Exception as exc:
                st.error(f"❌ Erreur : {exc}")


# ===========================================================
# INTERFACE ADMIN
# ===========================================================

# render_admin_login() remplacé par dashboard.auth.render_auth(cm)


def render_admin_panel():
    """Panneau admin complet — configuration de tous les modules."""
    settings = _get_settings()
    if not settings:
        err = st.session_state.get("_settings_error", "fichier introuvable ou YAML invalide")
        st.error(f"{t('cfg_load_error')} — {err}")
        return

    sub_tabs = st.tabs([
        f"⚙ {t('tab_llm')}",
        f"⛏ {t('tab_crawler')}",
        f"◈ {t('tab_news')}",
        f"⊛ {t('tab_sources')}",
        f"◇ {t('tab_mirofish')}",
        f"⚖ {t('tab_risk')}",
        f"⬡ {t('tab_agents')}",
        f"≡ {t('tab_logging')}",
        f"⇄ {t('tab_flux')}",
        f"👤 {t('tab_users')}",
    ])

    with sub_tabs[0]:  # LLM
        st.markdown(f'<h4><i class="fas fa-microchip" style="margin-right:7px;color:#7986cb;"></i>{t("cfg_llm_title")}</h4>', unsafe_allow_html=True)
        llm = settings.get("llm", {})
        col1, col2 = st.columns(2)
        with col1:
            _llm_providers = ["anthropic", "deepseek", "openai", "xai", "ollama"]
            _llm_default = llm.get("provider", "anthropic")
            if _llm_default not in _llm_providers:
                _llm_providers.append(_llm_default)
            llm["provider"] = st.selectbox(t("cfg_provider"), _llm_providers,
                index=_llm_providers.index(_llm_default))
            llm["model"] = st.text_input(t("cfg_model"), value=llm.get("model", "claude-3-5-sonnet-20241022"))
        with col2:
            llm["temperature"] = st.slider(t("cfg_temperature"), 0.0, 1.0,
                float(llm.get("temperature", 0.3)), 0.05)
            llm["max_tokens"] = st.number_input(t("cfg_max_tokens"), 512, 8192,
                int(llm.get("max_tokens", 4096)), step=512)
            llm["request_timeout_seconds"] = st.number_input(
                t("cfg_timeout_llm"),
                min_value=10, max_value=300,
                value=int(llm.get("request_timeout_seconds", 60)),
                step=10,
                help=t("cfg_timeout_help")
            )
        llm["cache_responses"] = st.toggle(t("cfg_cache_responses"), llm.get("cache_responses", True))
        settings["llm"] = llm

    with sub_tabs[1]:  # Crawler
        st.markdown(f'<h4><i class="fas fa-spider" style="margin-right:7px;color:#7986cb;"></i>{t("cfg_crawler_title")}</h4>', unsafe_allow_html=True)
        crawler = settings.get("crawler", {})
        col1, col2 = st.columns(2)
        with col1:
            _crawler_providers = ["tavily", "firecrawl", "serpapi", "duckduckgo"]
            _crawler_default = crawler.get("provider", "tavily")
            if _crawler_default not in _crawler_providers:
                _crawler_providers.append(_crawler_default)
            crawler["provider"] = st.selectbox(t("cfg_provider"), _crawler_providers,
                index=_crawler_providers.index(_crawler_default), key="crawler_provider")
            crawler["n_themes"] = st.slider(t("cfg_n_themes"), 5, 15, int(crawler.get("n_themes", 10)))
        with col2:
            crawler["max_pages_per_theme"] = st.slider(t("cfg_pages_theme"), 3, 20,
                int(crawler.get("max_pages_per_theme", 10)))
            _freq_opts = ["daily", "per_cycle", "trigger"]
            _freq_default = crawler.get("frequency", "daily")
            if _freq_default not in _freq_opts:
                _freq_opts.append(_freq_default)
            crawler["frequency"] = st.selectbox(t("cfg_frequency"), _freq_opts,
                index=_freq_opts.index(_freq_default))
        st.text_area(t("cfg_templates"),
            value="\n".join(crawler.get("templates", [])),
            key="crawler_templates", height=200)
        settings["crawler"] = crawler

    with sub_tabs[2]:  # News
        st.markdown(f'<h4><i class="fas fa-newspaper" style="margin-right:7px;color:#7986cb;"></i>{t("cfg_news_title")}</h4>', unsafe_allow_html=True)
        news = settings.get("news", {})
        col1, col2 = st.columns(2)
        with col1:
            news["polling_interval_seconds"] = st.slider(
                t("cfg_polling_interval"), 60, 3600,
                int(news.get("polling_interval_seconds", 900)), step=60
            )
        with col2:
            news["max_items_per_cycle"] = st.number_input(
                t("cfg_items_max_cycle"), 10, 200, int(news.get("max_items_per_cycle", 30))
            )
        # Mots-clés BTC
        kw = news.get("keywords_per_asset", {})
        btc_kw = kw.get("BTC/USDT", ["bitcoin", "BTC", "crypto"])
        new_kw = st.text_input(
            t("cfg_keywords_btc"),
            value=", ".join(btc_kw)
        )
        kw["BTC/USDT"] = [k.strip() for k in new_kw.split(",") if k.strip()]
        news["keywords_per_asset"] = kw
        settings["news"] = news

    with sub_tabs[3]:  # Sources
        st.markdown(f'<h4><i class="fas fa-satellite-dish" style="margin-right:7px;color:#7986cb;"></i>{t("cfg_sources_title")}</h4>', unsafe_allow_html=True)
        news = settings.get("news", {})

        # --- RSS ---
        st.markdown(f"#### 📰 {t('cfg_rss_title')}")
        rss_raw = "\n".join(news.get("sources_rss", []))
        rss_edited = st.text_area(
            t("cfg_rss_area"),
            value=rss_raw, height=300, key="rss_sources",
            help="Exemples : https://cointelegraph.com/rss"
        )
        news["sources_rss"] = [
            u.split("#")[0].strip()   # retire les commentaires inline
            for u in rss_edited.splitlines()
            if u.strip() and not u.strip().startswith("#")
        ]
        st.caption(t("cfg_rss_count").format(n=len(news['sources_rss'])))

        st.markdown("---")

        # --- Nitter ---
        st.markdown(f"#### 🐦 {t('cfg_nitter_title')}")
        nitter_raw = "\n".join(news.get("sources_nitter", []))
        nitter_edited = st.text_area(
            t("cfg_nitter_area"),
            value=nitter_raw, height=200, key="nitter_sources",
            help="Ex: saylor\nBitcoinMagazine\nwhale_alert"
        )
        news["sources_nitter"] = [
            u.strip().lstrip("@")
            for u in nitter_edited.splitlines()
            if u.strip()
        ]
        st.caption(t("cfg_nitter_count").format(n=len(news['sources_nitter'])))

        st.markdown("---")

        # --- Reddit ---
        st.markdown(f"#### 🤖 {t('cfg_reddit_title')}")
        reddit_raw = "\n".join(news.get("sources_reddit", []))
        reddit_edited = st.text_area(
            t("cfg_reddit_area"),
            value=reddit_raw, height=100, key="reddit_sources",
            help="Ex: Bitcoin\nCryptoCurrency\nbtc"
        )
        news["sources_reddit"] = [
            u.strip().lstrip("r/")
            for u in reddit_edited.splitlines()
            if u.strip()
        ]
        st.caption(t("cfg_reddit_count").format(n=len(news['sources_reddit'])))

        st.markdown("---")

        # --- CryptoPanic ---
        st.markdown("#### 🚨 CryptoPanic")
        cp = news.get("cryptopanic", {})
        col1, col2 = st.columns(2)
        with col1:
            cp["enabled"] = st.toggle(t("cfg_cp_enable"), cp.get("enabled", True))
        with col2:
            cp["max_items"] = st.number_input(
                t("cfg_cp_max"), 5, 50, int(cp.get("max_items", 15))
            )
        news["cryptopanic"] = cp

        settings["news"] = news

    with sub_tabs[4]:  # MiroFish
        st.markdown(f'<h4><i class="fas fa-fish" style="margin-right:7px;color:#7986cb;"></i>{t("cfg_mirofish_title")}</h4>', unsafe_allow_html=True)
        mf = settings.get("mirofish", {})
        col1, col2 = st.columns(2)
        with col1:
            mf["n_agents"] = st.number_input(t("cfg_mf_agents"), 1000, 50000,
                int(mf.get("n_agents", 5000)), step=1000)
            mf["n_steps"] = st.number_input(t("cfg_mf_steps"), 10, 500,
                int(mf.get("n_steps", 100)), step=10)
        with col2:
            mf["seed_news_weight"] = st.slider(t("cfg_mf_news_weight"), 0.0, 1.0,
                float(mf.get("seed_news_weight", 0.6)), 0.05)
            mf["air_du_temps_weight"] = 1 - mf["seed_news_weight"]
            st.metric(t("cfg_mf_adt_weight"), f"{mf['air_du_temps_weight']:.0%}")
        settings["mirofish"] = mf

    with sub_tabs[5]:  # Risk
        st.markdown(f'<h4><i class="fas fa-shield-halved" style="margin-right:7px;color:#7986cb;"></i>{t("cfg_risk_title")}</h4>', unsafe_allow_html=True)
        risk = settings.get("risk", {})
        col1, col2 = st.columns(2)
        with col1:
            _risk_modes = ["conservative", "balanced", "aggressive"]
            _risk_default = risk.get("mode", "balanced")
            if _risk_default not in _risk_modes:
                _risk_modes.append(_risk_default)
            risk["mode"] = st.selectbox("Mode", _risk_modes,
                index=_risk_modes.index(_risk_default))
            risk["kelly_max_fraction"] = st.slider(t("cfg_kelly_max"), 0.05, 0.50,
                float(risk.get("kelly_max_fraction", 0.25)), 0.05)
            risk["position_size_pct"] = st.slider(t("cfg_pos_size"), 1.0, 20.0,
                float(risk.get("position_size_pct", 5.0)), 0.5)
        with col2:
            risk["max_drawdown_pct"] = st.slider(t("cfg_max_dd"), 5.0, 50.0,
                float(risk.get("max_drawdown_pct", 15.0)), 1.0)
            risk["buy_threshold"] = st.slider(t("cfg_buy_threshold"), 50, 95,
                int(risk.get("buy_threshold", 70)))
            risk["sell_threshold"] = st.slider(t("cfg_exit_threshold"), 5, 50,
                int(risk.get("sell_threshold", 30)))
        risk["human_in_the_loop"] = st.toggle(t("cfg_hitl"),
            risk.get("human_in_the_loop", False))
        risk["max_open_positions"] = st.number_input(
            t("cfg_max_open_pos"),
            min_value=0, max_value=20,
            value=int(risk.get("max_open_positions", 3)),
            help=t("cfg_max_open_help")
        )

        st.markdown("---")
        st.markdown(f"**📊 {t('cfg_ma50_title')}**")
        ma50_mode = st.radio(
            t("cfg_ma50_mode"),
            options=["off", "gradual", "block"],
            index=["off", "gradual", "block"].index(risk.get("ma50_filter_mode", "gradual")),
            horizontal=True,
            help=(
                "**off** : aucun filtre, BUY toujours autorisés\n\n"
                "**gradual** : BUY bloqué si score < seuil fort ; autorisé mais taille réduite si score ≥ seuil fort\n\n"
                "**block** : BUY totalement bloqué quand prix < MA50"
            )
        )
        risk["ma50_filter_mode"] = ma50_mode
        if ma50_mode in ("gradual",):
            col_a, col_b = st.columns(2)
            risk["ma50_strong_signal_threshold"] = col_a.slider(
                t("cfg_ma50_score_min"), 70, 95,
                int(risk.get("ma50_strong_signal_threshold", 80)),
                help=t("cfg_ma50_score_help")
            )
            risk["ma50_gradual_size_factor"] = col_b.slider(
                t("cfg_ma50_size_factor"), 0.1, 1.0,
                float(risk.get("ma50_gradual_size_factor", 0.5)), 0.05,
                help=t("cfg_ma50_size_help")
            )

        settings["risk"] = risk

    with sub_tabs[6]:  # Agents
        st.markdown(f'<h4><i class="fas fa-network-wired" style="margin-right:7px;color:#7986cb;"></i>{t("cfg_agents_title")}</h4>', unsafe_allow_html=True)
        agents = settings.get("agents", {})
        for agent_name in ["market_data", "fundamental", "x_sentiment", "contrarian", "fear_greed", "polymarket"]:
            cfg = agents.get(agent_name, {})
            col1, col2 = st.columns([2, 1])
            with col1:
                cfg["enabled"] = st.toggle(t("cfg_agent_toggle").format(name=agent_name), cfg.get("enabled", True))
            with col2:
                cfg["weight_in_scoring"] = st.number_input(
                    t("cfg_agent_weight").format(name=agent_name), 0.0, 2.0,
                    float(cfg.get("weight_in_scoring", 1.0)), 0.1,
                    key=f"weight_{agent_name}"
                )
            agents[agent_name] = cfg
        settings["agents"] = agents

    with sub_tabs[7]:  # Logging
        st.markdown(f'<h4><i class="fas fa-list-check" style="margin-right:7px;color:#7986cb;"></i>{t("cfg_logging_title")}</h4>', unsafe_allow_html=True)
        log_cfg = settings.get("logging", {})
        _log_levels = ["DEBUG", "INFO", "WARNING", "ERROR"]
        _log_default = log_cfg.get("level", "INFO")
        if _log_default not in _log_levels:
            _log_levels.append(_log_default)
        log_cfg["level"] = st.selectbox(t("cfg_log_level"), _log_levels,
            index=_log_levels.index(_log_default))
        log_cfg["alert_score_threshold"] = st.slider(t("cfg_alert_threshold"),
            50, 100, int(log_cfg.get("alert_score_threshold", 85)))
        log_cfg["telegram_enabled"] = st.toggle("Telegram", log_cfg.get("telegram_enabled", False))
        log_cfg["discord_enabled"] = st.toggle("Discord", log_cfg.get("discord_enabled", False))
        settings["logging"] = log_cfg

    with sub_tabs[8]:  # Flux Manager
        render_flux_manager_page()
        # pas de bouton save ici, géré dans flux_manager

    with sub_tabs[9]:  # Utilisateurs
        from dashboard.auth import render_users_admin
        render_users_admin()
        # sauvegarde gérée dans render_users_admin

    # Bouton de sauvegarde (pour tous les onglets sauf Flux Manager)
    st.markdown("---")
    if st.button(t('save_config_btn'), type="primary", use_container_width=True):
        if _save_settings(settings):
            st.success(f"✅ {t('config_saved')}")
        else:
            st.error(f"❌ {t('config_error')}")


# ===========================================================
# PAGE PRINCIPALE
# ===========================================================

def main():
    # ── Cookie manager (init AVANT tout rendu Streamlit) ──────────────────────
    import extra_streamlit_components as stx
    cm = stx.CookieManager(key="atlas_cm")

    _init_session()

    # ── Authentification ──────────────────────────────────────────────────────
    # Stratégie : session serveur (dict Python) via ?_sid= dans l'URL.
    # Aucune dépendance au timing du composant CookieManager React.
    # La session est créée dans _finalize_login() et éteinte via logout().
    from dashboard.auth import get_session, has_role, render_auth, logout, load_users_config
    session = get_session(cm)
    st.session_state["admin_authenticated"] = has_role(session, "back")
    st.session_state["username"] = session.get("username", "") if session else ""

    users_cfg = load_users_config()
    guest_mode = users_cfg.get("settings", {}).get("guest_mode", True)

    _inject_theme_css()
    render_header()

    show_admin = st.query_params.get("admin", "0") == "1"

    if show_admin:
        # ── VUE ADMINISTRATION ──
        if not has_role(session, "back"):
            st.markdown(
                f'<h3 style="margin:0 0 12px;font-size:18px;"><i class="fas fa-lock" '
                f'style="margin-right:8px;color:#e74c3c;"></i>{t("admin_title")}</h3>',
                unsafe_allow_html=True,
            )
            st.info(t("admin_auth_required"))
            render_auth(cm)
        else:
            render_admin_panel()
    else:
        # ── VUE DASHBOARD ──
        if not guest_mode and not has_role(session, "front"):
            # Front protégé
            render_auth(cm)
        else:
            last_cycle = _get_last_cycle()
            portfolio  = _get_portfolio()
            _get_pnl_history()

            render_portfolio(portfolio)
            render_climate_metrics(last_cycle)

            recent_trades = _get_recent_trades()
            render_last_decision(last_cycle)
            render_pnl_chart(recent_trades)
            render_btc_live_chart()
            render_trades_list(recent_trades)
            render_live_logs()

    # Auto-refresh toutes les 30s — préserve les query params dont _sid
    time.sleep(0.1)
    _sid_js = st.session_state.get("_session_id", "")
    st.markdown(
        f"<script>setTimeout(function(){{window.location.href=window.location.href;}}, 30000);</script>",
        unsafe_allow_html=True
    )


if __name__ == "__main__":
    main()
