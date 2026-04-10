"""
dashboard/multi_asset.py — Composants UI multi-actifs pour Streamlit.

Exposés :
  - render_global_overview()    : tableau consolidé de tous les actifs actifs
  - render_asset_tabs(main_fn)  : wrapper qui injecte les onglets par actif
  - render_marches_admin_tab()  : sous-onglet "🌐 Marchés" du panneau admin
"""
from __future__ import annotations

import time
from typing import Callable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _active_assets() -> list[str]:
    """Retourne la liste des actifs actifs depuis la config."""
    try:
        from utils.config import get_active_assets
        return get_active_assets()
    except Exception:
        return ["BTC/USDT"]


def _asset_icon(asset: str) -> str:
    """Emoji / lettre pour chaque actif."""
    icons = {
        "BTC/USDT": "₿",
        "ETH/USDT": "⟠",
        "SOL/USDT": "◎",
        "XAU/USD":  "🥇",
        "XAG/USD":  "🥈",
        "WTI/USD":  "🛢️",
        "EUR/USD":  "€",
        "GBP/USD":  "£",
        "USD/JPY":  "¥",
    }
    return icons.get(asset, "◈")


def _action_badge(action: str) -> str:
    colors = {"BUY": "#27ae60", "SELL": "#e74c3c", "HOLD": "#888888"}
    color = colors.get(action, "#888888")
    return f'<span style="background:{color};color:#fff;border-radius:3px;padding:1px 7px;font-size:12px;">{action}</span>'


def _score_bar(score: float) -> str:
    """Mini barre de progression HTML pour le score."""
    color = "#27ae60" if score >= 60 else ("#e74c3c" if score < 40 else "#f39c12")
    return (
        f'<div style="display:flex;align-items:center;gap:6px;">'
        f'<div style="width:80px;height:8px;background:#333;border-radius:4px;overflow:hidden;">'
        f'<div style="width:{score:.0f}%;height:100%;background:{color};border-radius:4px;"></div>'
        f'</div>'
        f'<span style="font-size:13px;">{score:.0f}</span>'
        f'</div>'
    )


# ---------------------------------------------------------------------------
# Composant 1 : Vue globale
# ---------------------------------------------------------------------------

def render_global_overview() -> None:
    """
    Tableau consolidé multi-actifs affiché en tête de la vue Globale.
    Montre : Actif | Dernier signal | Score | Timestamp | P&L 24h
    """
    import streamlit as st

    try:
        from storage.database import get_assets_summary
        from utils.session import MarketSession
        db_rows = get_assets_summary()
    except Exception as exc:
        st.warning(f"Données globales indisponibles : {exc}")
        return

    # Fusionner avec tous les actifs actifs (afficher même sans décision en base)
    db_by_asset = {r["asset"]: r for r in db_rows}
    all_assets = _active_assets()
    rows = []
    for asset in all_assets:
        if asset in db_by_asset:
            rows.append(db_by_asset[asset])
        else:
            rows.append({"asset": asset, "action": "–", "score": None, "timestamp": None, "result_24h": None})

    st.markdown("### 🌐 Vue globale des actifs")

    # Enrichir avec le statut de session
    html_rows = ""
    for r in rows:
        asset   = r.get("asset", "?")
        action  = r.get("action", "HOLD")
        score   = float(r.get("score") or 50)
        ts      = (r.get("timestamp") or "")[:16]
        pnl     = r.get("result_24h")
        icon    = _asset_icon(asset)

        # Session status
        try:
            sess = MarketSession(asset)
            sess_label = sess.status_label()
        except Exception:
            sess_label = "–"

        pnl_str = (
            f'<span style="color:#27ae60">+{pnl:.1f}%</span>'
            if pnl and pnl > 0
            else (f'<span style="color:#e74c3c">{pnl:.1f}%</span>'
                  if pnl and pnl < 0
                  else "–")
        )
        html_rows += (
            f"<tr>"
            f"<td style='padding:6px 10px;'>{icon} {asset}</td>"
            f"<td style='padding:6px 10px;'>{_action_badge(action)}</td>"
            f"<td style='padding:6px 10px;'>{_score_bar(score)}</td>"
            f"<td style='padding:6px 10px;font-size:12px;opacity:.7;'>{ts}</td>"
            f"<td style='padding:6px 10px;'>{pnl_str}</td>"
            f"<td style='padding:6px 10px;font-size:12px;'>{sess_label}</td>"
            f"</tr>"
        )

    st.markdown(
        f"""<table style="width:100%;border-collapse:collapse;">
        <thead><tr style="border-bottom:1px solid #444;font-size:12px;opacity:.6;">
          <th style="padding:4px 10px;text-align:left;">Actif</th>
          <th style="padding:4px 10px;text-align:left;">Signal</th>
          <th style="padding:4px 10px;text-align:left;">Score</th>
          <th style="padding:4px 10px;text-align:left;">Horodatage</th>
          <th style="padding:4px 10px;text-align:left;">P&L 24h</th>
          <th style="padding:4px 10px;text-align:left;">Session</th>
        </tr></thead>
        <tbody>{html_rows}</tbody>
        </table>""",
        unsafe_allow_html=True,
    )
    st.markdown("---")


# ---------------------------------------------------------------------------
# Composant 1b : Prix live multi-actifs (cartes)
# ---------------------------------------------------------------------------

def render_global_live_prices() -> None:
    """Grille de prix live pour tous les actifs actifs (appel MarketDataAgent)."""
    import streamlit as st

    assets = _active_assets()
    if not assets:
        return

    st.markdown("### 📡 Prix temps réel")

    try:
        from agents.market_data_agent import MarketDataAgent
        agent = MarketDataAgent()
    except Exception as exc:
        st.caption(f"Prix indisponibles : {exc}")
        return

    cols = st.columns(min(len(assets), 5))
    for i, asset in enumerate(assets):
        icon = _asset_icon(asset)
        try:
            ind   = agent.get_indicators(asset)
            price = ind.get("price", 0)
            ma50  = ind.get("ma_50", 0)
            rsi   = ind.get("rsi_14", 50)
            above = ind.get("above_ma50")
            src   = ind.get("_source", "ccxt")
            delta_str = None
            if ma50 and price:
                delta_pct = (price / ma50 - 1) * 100
                # Ne pas afficher si > ±30% : signe probable de roll de contrat (futures)
                if abs(delta_pct) <= 30:
                    delta_str = f"{delta_pct:+.1f}% vs MA50"
                elif src == "yahoo":
                    delta_str = None  # roll artifact — masqué
                else:
                    delta_str = f"{delta_pct:+.1f}% vs MA50"
            delta = delta_str
            rsi_tag = (
                "🟢" if rsi >= 60 else "🔴" if rsi <= 40 else "🟡"
            )
            with cols[i % len(cols)]:
                # Format lisible selon l'ordre de grandeur
                if price >= 1000:
                    price_str = f"{price:,.0f}"
                elif price >= 1:
                    price_str = f"{price:,.2f}"
                elif price >= 0.001:
                    price_str = f"{price:,.4f}"
                else:
                    price_str = f"{price:.6f}"
                st.metric(
                    label=f"{icon} {asset}",
                    value=price_str,
                    delta=delta,
                )
                st.caption(f"RSI {rsi_tag} {rsi:.0f} · {'▲ MA50' if above else '▼ MA50' if above is not None else '—'}")
        except Exception:
            with cols[i % len(cols)]:
                st.metric(f"{icon} {asset}", "—")
    st.markdown("---")


# ---------------------------------------------------------------------------
# Composant 2 : Onglets par actif
# ---------------------------------------------------------------------------

def render_asset_tabs(
    render_fn: Callable[[str], None],
    global_fn: "Callable[[], None] | None" = None,
    pre_global_fn: "Callable[[], None] | None" = None,
) -> None:
    """
    Navigation via la sidebar Streamlit native (sticky, pliable/dépliable).
    Si un seul actif est actif, passe directement à render_fn sans navigation.
    """
    import streamlit as st

    assets = _active_assets()

    if len(assets) <= 1:
        asset = assets[0] if assets else "BTC/USDT"
        render_fn(asset)
        return

    labels = ["🌐 Global"] + [f"{_asset_icon(a)}  {a}" for a in assets]

    # ── Force la sidebar ouverte (une seule fois par session) ────────────────
    # Le localStorage du navigateur peut mémoriser l'état "collapsed" d'une
    # session précédente et écraser initial_sidebar_state="expanded".
    # On nettoie ce localStorage et on clique le bouton d'ouverture via JS.
    if not st.session_state.get("_sidebar_forced_open"):
        st.session_state["_sidebar_forced_open"] = True
        import streamlit.components.v1 as _cv1
        _cv1.html("""<script>
(function(){
  try {
    var p = window.parent;
    // 1. Effacer les clés sidebar du localStorage pour les prochains rechargements
    Object.keys(p.localStorage).forEach(function(k){
      if (/sidebar/i.test(k)) p.localStorage.removeItem(k);
    });
    // 2. MutationObserver : dès que le bouton "ouvrir" apparaît, le cliquer
    function tryExpand(){
      var d = p.document;
      // Plusieurs sélecteurs pour couvrir différentes versions de Streamlit
      var selectors = [
        '[data-testid="stSidebarCollapsedControl"] button',
        '[data-testid="stSidebarToggleButton"]',
        'button[kind="header"][aria-label*="sidebar"]',
        'button[aria-label*="open sidebar"]',
        'button[aria-label*="Open sidebar"]',
      ];
      for (var i = 0; i < selectors.length; i++){
        var btn = d.querySelector(selectors[i]);
        if (btn){ btn.click(); return true; }
      }
      return false;
    }
    if (!tryExpand()){
      var obs = new p.MutationObserver(function(){
        if (tryExpand()) obs.disconnect();
      });
      obs.observe(p.document.body, {childList:true, subtree:true});
      setTimeout(function(){ obs.disconnect(); }, 6000);
    }
  } catch(e){ console.warn('sidebar-open:', e); }
})();
</script>""", height=0, scrolling=False)

    with st.sidebar:
        st.markdown(
            "<p style='font-size:11px;font-weight:700;letter-spacing:1.5px;"
            "opacity:.5;margin:16px 0 8px;text-transform:uppercase;'>Actifs</p>",
            unsafe_allow_html=True,
        )
        selected = st.radio(
            "Actif",
            labels,
            key="_asset_nav",
            label_visibility="collapsed",
        )

    if selected == "🌐 Global":
        if pre_global_fn is not None:
            pre_global_fn()
        render_global_overview()
        render_global_live_prices()
        if global_fn is not None:
            global_fn()
    else:
        idx = labels.index(selected)
        render_fn(assets[idx - 1])



# ---------------------------------------------------------------------------
# Composant 3 : Sous-onglet Admin "🌐 Marchés"
# ---------------------------------------------------------------------------

def render_marches_admin_tab() -> None:
    """
    Sous-onglet Admin permettant de configurer chaque actif individuellement.
    - Seuils buy/exit par actif
    - Agents on/off par actif
    - Hot-reload (signal SIGHUP ou rechargement config en mémoire)
    """
    import streamlit as st

    st.markdown("#### 🌐 Configuration des marchés actifs")
    st.caption(
        "Modifier les paramètres par actif. Les changements sont sauvegardés dans "
        "`config/assets/{slug}.yaml` et pris en compte au prochain cycle."
    )

    try:
        from utils.config import get_active_assets, load_asset_config, save_asset_config
    except ImportError as exc:
        st.error(f"Import config échoué : {exc}")
        return

    # Ajouter/retirer un actif de active_assets
    st.markdown("""<style>
/* Fix troncature des tags dans le multiselect "Actifs surveillés" */
[data-testid="stMultiSelect"] span[data-baseweb="tag"] {
    min-width: 90px !important;
    max-width: none !important;
    padding-left: 10px !important;
    padding-right: 10px !important;
}
[data-testid="stMultiSelect"] span[data-baseweb="tag"] span:first-child {
    overflow: visible !important;
    white-space: nowrap !important;
    text-overflow: unset !important;
}
</style>""", unsafe_allow_html=True)
    st.markdown("**Actifs actifs**")
    all_known = ["BTC/USDT", "ETH/USDT", "XAU/USD", "EUR/USD", "GBP/USD"]
    current_active = get_active_assets()
    new_active = st.multiselect(
        "Actifs surveillés",
        options=all_known,
        default=current_active,
        help="Seuls les actifs ayant un fichier config/assets/*.yaml sont supportés.",
        key="marches_active_assets",
    )

    if st.button("💾 Sauvegarder la liste des actifs", key="btn_save_active_assets"):
        try:
            from utils.config import load_settings, save_settings
            from pathlib import Path
            cfg_path = Path(__file__).parent.parent / "config" / "settings.yaml"
            settings = load_settings(cfg_path)
            settings.setdefault("project", {})["active_assets"] = new_active
            save_settings(settings, cfg_path)
            st.success(f"Liste sauvegardée : {', '.join(new_active)}")
        except Exception as exc:
            st.error(f"Erreur sauvegarde : {exc}")

    st.markdown("---")

    # Paramètres par actif
    for asset in current_active:
        _render_asset_config_editor(asset, load_asset_config, save_asset_config)


def _render_asset_config_editor(
    asset: str,
    load_fn: Callable,
    save_fn: Callable,
) -> None:
    """Formulaire d'édition de la config d'un actif."""
    import streamlit as st

    icon = _asset_icon(asset)
    slug = asset.replace("/", "_")

    with st.expander(f"{icon} **{asset}**", expanded=False):
        try:
            cfg = load_fn(asset)
        except Exception as exc:
            st.warning(f"Config {asset} non chargée : {exc}")
            return

        risk = cfg.get("risk", {})
        agents = cfg.get("agents", {})

        # Capital paper par actif
        col0, = st.columns([1])  # ligne entière
        paper_cap = st.number_input(
            "💰 Capital paper (USD)",
            min_value=500, max_value=1_000_000, step=500,
            value=int(cfg.get("paper_capital_usd", 10000)),
            key=f"paper_cap_{slug}",
            help=(
                "Montant alloué à cet actif en mode paper trading. "
                "En production, le solde est lu depuis l'API de l'exchange."
            ),
        )

        col1, col2, col3 = st.columns(3)
        with col1:
            buy_thr = st.number_input(
                "Buy threshold",
                min_value=30, max_value=95, step=1,
                value=int(risk.get("buy_threshold", 62)),
                key=f"buy_thr_{slug}",
            )
        with col2:
            exit_thr = st.number_input(
                "Exit threshold",
                min_value=20, max_value=80, step=1,
                value=int(risk.get("exit_threshold", 52)),
                key=f"exit_thr_{slug}",
            )
        with col3:
            pos_pct = st.number_input(
                "Position size %",
                min_value=0.5, max_value=20.0, step=0.5,
                value=float(risk.get("position_size_pct", 5.0)),
                key=f"pos_pct_{slug}",
            )

        # Agents on/off
        st.caption("Agents")
        agent_cols = st.columns(4)
        agent_names = [
            ("fundamental", "Fundamental"),
            ("x_sentiment", "Sentiment"),
            ("contrarian", "Contrarian"),
            ("fear_greed", "Fear&Greed"),
            ("polymarket", "Polymarket"),
            ("timesfm", "TimesFM"),
            ("market_regime", "Régime"),
            ("bull_bear_debate", "BullBear"),
        ]
        agent_states: dict[str, bool] = {}
        for i, (key, label) in enumerate(agent_names):
            with agent_cols[i % 4]:
                enabled = agents.get(key, {}).get("enabled", True)
                agent_states[key] = st.checkbox(label, value=enabled, key=f"agent_{slug}_{key}")

        if st.button(f"💾 Sauvegarder {asset}", key=f"save_{slug}"):
            # Reconstruire la section risk
            cfg.setdefault("risk", {}).update({
                "buy_threshold": buy_thr,
                "exit_threshold": exit_thr,
                "position_size_pct": pos_pct,
            })
            cfg["paper_capital_usd"] = paper_cap
            for key, enabled in agent_states.items():
                cfg.setdefault("agents", {}).setdefault(key, {})["enabled"] = enabled
            try:
                save_fn(asset, cfg)
                st.success(f"Config {asset} sauvegardée.")
            except Exception as exc:
                st.error(f"Erreur : {exc}")
