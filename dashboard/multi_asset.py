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

from utils.i18n import t


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

_ACTION_TO_DIR = {"long": 75, "short": 25, "flat": 50, "hold": 50}

def render_global_overview() -> None:
    """
    Tableau consolidé multi-actifs affiché en tête de la vue Globale.
    V2 : lit v2_equity (dernière ligne par actif). Fallback sur decisions V1 si vide.
    """
    import streamlit as st

    try:
        from storage.database import get_v2_assets_summary, get_assets_summary
        from utils.session import MarketSession
        db_rows = get_v2_assets_summary()
        is_v2 = bool(db_rows)
        if not is_v2:
            db_rows = get_assets_summary()
    except Exception as exc:
        st.warning(f'{t("global_data_unavailable")} : {exc}')
        return

    db_by_asset = {r["asset"]: r for r in db_rows}
    all_assets = _active_assets()
    rows = []
    for asset in all_assets:
        if asset in db_by_asset:
            rows.append(db_by_asset[asset])
        else:
            rows.append({"asset": asset, "action": "flat", "score": None,
                         "equity": None, "timestamp": None, "result_24h": None})

    st.markdown(f"### {t('global_overview_title')}")

    extra_hdr = "Capital V2" if is_v2 else t('col_pnl')
    html_rows = ""
    for r in rows:
        asset  = r.get("asset", "?")
        action = (r.get("action") or "flat").lower()
        # V2 : direction basée sur l'action (LONG=75, SHORT=25, FLAT=50)
        # V1 fallback : score 0-100 depuis decisions
        if is_v2:
            score = _ACTION_TO_DIR.get(action, 50)
        else:
            score = float(r.get("score") or 50)
        ts    = (r.get("ts") or r.get("timestamp") or "")[:16]
        icon  = _asset_icon(asset)

        # Capital V2 ou P&L V1
        if is_v2:
            equity = r.get("equity")
            extra_str = (f'<span style="font-size:12px;">${equity:,.0f}</span>' if equity else "—")
        else:
            pnl = r.get("result_24h")
            extra_str = (
                f'<span style="color:#27ae60">+{pnl:.1f}%</span>' if pnl and pnl > 0
                else (f'<span style="color:#e74c3c">{pnl:.1f}%</span>' if pnl and pnl < 0 else "—")
            )
        # Session status
        try:
            sess = MarketSession(asset)
            sess_label = sess.status_label()
        except Exception:
            sess_label = "–"

        html_rows += (
            f"<tr>"
            f"<td style='padding:6px 10px;'>{icon} {asset}</td>"
            f"<td style='padding:6px 10px;'>{_action_badge(action)}</td>"
            f"<td style='padding:6px 10px;'>{_score_bar(score)}</td>"
            f"<td style='padding:6px 10px;font-size:12px;opacity:.7;'>{ts}</td>"
            f"<td style='padding:6px 10px;'>{extra_str}</td>"
            f"<td style='padding:6px 10px;font-size:12px;'>{sess_label}</td>"
            f"</tr>"
        )

    st.markdown(
        f"""<table style="width:100%;border-collapse:collapse;">
        <thead><tr style="border-bottom:1px solid #444;font-size:12px;opacity:.6;">
          <th style="padding:4px 10px;text-align:left;">{t('col_asset')}</th>
          <th style="padding:4px 10px;text-align:left;">{t('col_signal')}</th>
          <th style="padding:4px 10px;text-align:left;">{"Direction V2" if is_v2 else t('col_score')}</th>
          <th style="padding:4px 10px;text-align:left;">{t('col_timestamp')}</th>
          <th style="padding:4px 10px;text-align:left;">{extra_hdr}</th>
          <th style="padding:4px 10px;text-align:left;">{t('col_session')}</th>
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
    """Grille de prix live pour tous les actifs actifs — V2 : CCXT direct."""
    import streamlit as st

    assets = _active_assets()
    if not assets:
        return

    st.markdown(f"### {t('live_prices_title')}")

    try:
        from quant.data_loader import fetch_ohlcv, _YAHOO_SYMBOLS as _NON_BINANCE
    except Exception as exc:
        st.caption(f"Prix indisponibles : {exc}")
        return

    # Prix en DB pour les actifs non-Binance (forex/commodités) — non-bloquant
    _db_prices: dict[str, float] = {}
    try:
        from storage.database import get_v2_assets_summary
        for _row in get_v2_assets_summary():
            if _row.get("close_price"):
                _db_prices[_row["asset"]] = float(_row["close_price"])
    except Exception:
        pass

    cols = st.columns(min(len(assets), 5))
    for i, asset in enumerate(assets):
        icon = _asset_icon(asset)

        # Actifs non-Binance (forex/commodités) → prix depuis DB (mis à jour par le daemon)
        if asset in _NON_BINANCE:
            price = _db_prices.get(asset)
            with cols[i % len(cols)]:
                if price and price > 0:
                    if price >= 1000:
                        price_str = f"{price:,.0f}"
                    elif price >= 1:
                        price_str = f"{price:,.2f}"
                    elif price >= 0.001:
                        price_str = f"{price:,.4f}"
                    else:
                        price_str = f"{price:.6f}"
                    st.metric(label=f"{icon} {asset}", value=price_str)
                    st.caption("Dernier prix connu")
                else:
                    st.metric(label=f"{icon} {asset}", value="—")
                    st.caption("En attente du cycle")
            continue

        try:
            bars = fetch_ohlcv(symbol=asset, timeframe="15m", limit=52)
            if bars is None or bars.empty:
                raise ValueError("Aucune barre")
            price = float(bars["close"].iloc[-1])
            ma50  = float(bars["close"].tail(50).mean()) if len(bars) >= 50 else None
            closes = bars["close"].values.astype(float)
            # RSI rapide (14)
            if len(closes) >= 15:
                deltas = [closes[j] - closes[j-1] for j in range(1, len(closes))]
                gains = [max(d, 0) for d in deltas[-14:]]
                losses = [max(-d, 0) for d in deltas[-14:]]
                avg_gain = sum(gains) / 14
                avg_loss = sum(losses) / 14
                rsi = 100 - 100 / (1 + avg_gain / avg_loss) if avg_loss else 100.0
            else:
                rsi = 50.0
            above = price > ma50 if ma50 else None
            delta_str = None
            if ma50 and price:
                delta_pct = (price / ma50 - 1) * 100
                if abs(delta_pct) <= 30:
                    delta_str = f"{delta_pct:+.1f}% vs MA50"
            rsi_tag = "🟢" if rsi >= 60 else "🔴" if rsi <= 40 else "🟡"
            with cols[i % len(cols)]:
                if price >= 1000:
                    price_str = f"{price:,.0f}"
                elif price >= 1:
                    price_str = f"{price:,.2f}"
                elif price >= 0.001:
                    price_str = f"{price:,.4f}"
                else:
                    price_str = f"{price:.6f}"
                st.metric(label=f"{icon} {asset}", value=price_str, delta=delta_str)
                st.caption(
                    f"RSI {rsi_tag} {rsi:.0f} · "
                    f"{'▲ MA50' if above else '▼ MA50' if above is not None else '—'}"
                )
        except Exception:
            with cols[i % len(cols)]:
                st.metric(f"{icon} {asset}", "—")
    st.markdown("---")


# ---------------------------------------------------------------------------
# Composant 2 : Onglets par actif
# ---------------------------------------------------------------------------

def _inject_custom_sidenav(items: list, active_key: str, qparam: str = "_asset") -> None:
    """Injecte une sidebar fixe dans le document parent (indépendante de st.sidebar).
    items  : liste de dicts {key, icon, text}
    active_key : clé de l'item actif
    qparam : nom du query parameter utilisé pour la navigation
    """
    import json as _json
    import streamlit.components.v1 as _cv1

    items_js  = _json.dumps(items)
    active_js = _json.dumps(active_key)
    qparam_js = _json.dumps(qparam)

    _cv1.html(f"""<script>
(function(){{
  var p = window.parent, d = p.document;
  var ACTIVE = {active_js};
  var ITEMS  = {items_js};
  var QPARAM = {qparam_js};
  var W = 180, MINI = 44;

  /* Hauteur du header Streamlit (mesurée dynamiquement) */
  function hdrH() {{
    var h = d.querySelector('[data-testid="stHeader"]');
    return (h && h.getBoundingClientRect().height > 10)
           ? h.getBoundingClientRect().height : 60;
  }}

  var collapsed = p.localStorage.getItem('atlas_nav_c') === '1';

  /* ── CSS dropdown injecte dans le HEAD parent (les popovers sont portales dans le parent) ── */
  if (!d.getElementById('atlas-dropdown-css')) {{
    var dropS = d.createElement('style');
    dropS.id = 'atlas-dropdown-css';
    dropS.textContent = [
      '[data-baseweb="popover"] {{ min-width: max-content !important; }}',
      'ul[data-baseweb="menu"] li, [data-baseweb="option"] {{ white-space: nowrap !important; }}'
    ].join(' ');
    d.head.appendChild(dropS);
  }}

  function navUrl(key) {{
    var u = new URL(p.location.href);
    u.searchParams.set(QPARAM, key);
    return u.toString();
  }}

  function setPad(c) {{
    var w = (c ? MINI : W) + 'px';
    /* Style tag persistant dans <head> — immune aux rerenders React de Streamlit,
       contrairement aux inline styles qui sont réinitialisés à chaque widget interaction. */
    var padS = d.getElementById('atlas-pad-css');
    if (!padS) {{ padS = d.createElement('style'); padS.id = 'atlas-pad-css'; d.head.appendChild(padS); }}
    padS.textContent = '[data-testid="stAppViewContainer"]{{padding-left:' + w + '!important;}}';
  }}

  function positionNav(nav) {{
    if (!nav) return;
    var top = hdrH();
    nav.style.top = top + 'px';
    nav.style.height = 'calc(100vh - ' + top + 'px)';
  }}

  /* CSS — injecté une seule fois */
  if (!d.getElementById('atlas-nav-css')) {{
    var s = d.createElement('style');
    s.id = 'atlas-nav-css';
    s.textContent =
      '#atlas-sidenav{{position:fixed;left:0;' +
      'width:' + W + 'px;background:#161b22;z-index:100;' +
      'display:flex;flex-direction:column;' +
      'border-right:1px solid rgba(255,255,255,.12);' +
      'transition:width .2s ease;overflow:hidden;box-sizing:border-box;}}' +
      '#atlas-sidenav.c{{width:' + MINI + 'px;}}' +
      '#ant{{display:flex;align-items:center;justify-content:flex-end;height:34px;' +
      'padding:0 10px;cursor:pointer;border-bottom:1px solid rgba(255,255,255,.07);' +
      'color:rgba(255,255,255,.5);font-size:17px;user-select:none;flex-shrink:0;}}' +
      '#atlas-sidenav.c #ant{{justify-content:center;padding:0;}}' +
      '.ans{{font-size:8px;font-weight:700;letter-spacing:1.5px;opacity:.35;' +
      'text-transform:uppercase;padding:6px 12px 1px;color:#fff;white-space:nowrap;flex-shrink:0;}}' +
      '#atlas-sidenav.c .ans{{display:none;}}' +
      '.ani{{display:flex;align-items:center;gap:7px;padding:4px 8px;text-decoration:none;' +
      'color:rgba(255,255,255,.75);font-size:12px;' +
      'font-family:-apple-system,BlinkMacSystemFont,sans-serif;' +
      'border-radius:5px;margin:0 4px;white-space:nowrap;transition:background .15s;}}' +
      '#atlas-sidenav.c .ani{{justify-content:center;padding:6px 0;margin:0;border-radius:0;}}' +
      '.ani:hover{{background:rgba(255,255,255,.08);color:#fff;}}' +
      '.ani.a{{background:rgba(255,75,75,.22);font-weight:600;color:#fff;}}' +
      '.ani-ic{{font-size:17px;min-width:24px;text-align:center;flex-shrink:0;line-height:1;}}' +
      '#atlas-sidenav.c .ani-ic{{min-width:' + MINI + 'px;font-size:15px;}}' +
      '.ani-tx{{white-space:nowrap;overflow:hidden;transition:opacity .15s;}}' +
      '#atlas-sidenav.c .ani-tx{{opacity:0;width:0;pointer-events:none;position:absolute;}}';
    d.head.appendChild(s);
  }}

  /* Construction du nav */
  var existing = d.getElementById('atlas-sidenav');
  var wasC = existing ? existing.classList.contains('c') : collapsed;
  var nav = d.createElement('div');
  nav.id = 'atlas-sidenav';
  if (wasC) nav.classList.add('c');

  nav.innerHTML =
    '<div id="ant" title="Réduire / Agrandir">&#9776;</div>' +
    ITEMS.map(function(it) {{
      if (it.section) {{
        return '<div class="ans">' + it.section + '</div>';
      }}
      var cls = 'ani' + (it.key === ACTIVE ? ' a' : '');
      return '<a class="' + cls + '" href="' + navUrl(it.key) + '" title="' + it.text + '">' +
             '<span class="ani-ic">' + it.icon + '</span>' +
             '<span class="ani-tx">' + it.text + '</span></a>';
    }}).join('');

  if (existing) existing.replaceWith(nav);
  else d.body.appendChild(nav);

  positionNav(nav);
  setTimeout(function() {{ positionNav(d.getElementById('atlas-sidenav')); }}, 200);
  setTimeout(function() {{ positionNav(d.getElementById('atlas-sidenav')); }}, 700);
  setPad(wasC);

  /* Re-positionner si le header change de taille */
  var ro = new p.ResizeObserver(function() {{ positionNav(d.getElementById('atlas-sidenav')); }});
  var hdrEl = d.querySelector('[data-testid="stHeader"]');
  if (hdrEl) ro.observe(hdrEl);

  d.getElementById('ant').addEventListener('click', function() {{
    var n = d.getElementById('atlas-sidenav');
    var c = n.classList.toggle('c');
    p.localStorage.setItem('atlas_nav_c', c ? '1' : '0');
    setPad(c);
  }});

  /* ── Fix BaseWeb dropdown width — supprime le width inline injecte par useEffect ── */
  if (!p._atlasDropMo) {{
    /* Fixe un popover : supprime width + observe les reecritures ulterieures */
    function _atlasFixPop(el) {{
      el.style.removeProperty('width');
      el.style.minWidth = 'max-content';
      if (!el._atlasWatched) {{
        el._atlasWatched = true;
        new p.MutationObserver(function() {{
          if (el.style.width) {{
            el.style.removeProperty('width');
            el.style.minWidth = 'max-content';
          }}
        }}).observe(el, {{ attributes: true, attributeFilter: ['style'] }});
      }}
    }}
    p._atlasDropMo = new p.MutationObserver(function(muts) {{
      muts.forEach(function(m) {{
        m.addedNodes.forEach(function(node) {{
          if (!node.querySelectorAll) return;
          /* Cas 1 : le popover lui-meme est ajoute */
          if (node.getAttribute && node.getAttribute('data-baseweb') === 'popover') {{
            _atlasFixPop(node);
          }}
          /* Cas 1b : popover comme descendant */
          Array.prototype.slice.call(
            node.querySelectorAll('[data-baseweb="popover"]')
          ).forEach(_atlasFixPop);
          /* Cas 2 : le menu est ajoute dans un popover deja existant (rendu differe) */
          var menus = node.getAttribute && node.getAttribute('data-baseweb') === 'menu'
            ? [node]
            : Array.prototype.slice.call(node.querySelectorAll('ul[data-baseweb="menu"]'));
          menus.forEach(function(menu) {{
            var pop = menu.closest ? menu.closest('[data-baseweb="popover"]') : null;
            if (pop) _atlasFixPop(pop);
          }});
        }});
      }});
    }});
    p._atlasDropMo.observe(d.body, {{ childList: true, subtree: true }});
  }}
}})();
</script>""", height=0, scrolling=False)


def render_asset_tabs(
    render_fn: Callable[[str], None],
    global_fn: "Callable[[], None] | None" = None,
    pre_global_fn: "Callable[[], None] | None" = None,
) -> None:
    """
    Menu latéral fixe (position:fixed dans le DOM parent) — sticky, pliable/dépliable.
    Navigation via query param _asset, sans aucune dépendance à st.sidebar.
    Si un seul actif est actif, passe directement à render_fn sans navigation.
    """
    import streamlit as st

    assets = _active_assets()

    if len(assets) <= 1:
        render_fn(assets[0] if assets else "BTC/USDT")
        return

    # Double espace entre icone et texte pour le split → "🌐  Global", "₿  BTC/USDT"
    labels = ["🌐  Global"] + [f"{_asset_icon(a)}  {a}" for a in assets]
    # Clés URL-safe (ex: "BTC_USDT")
    keys   = ["Global"] + [a.replace("/", "_") for a in assets]

    # Sélection lue depuis l'URL (persistée, pas de localStorage Streamlit)
    selected_key = st.query_params.get("_asset", "Global")
    if selected_key not in keys:
        selected_key = "Global"

    # Items pour le JS [{key, icon, text}, ...]
    items = []
    for k, lbl in zip(keys, labels):
        parts = lbl.split("  ", 1)
        items.append({"key": k, "icon": parts[0], "text": parts[1] if len(parts) > 1 else parts[0]})

    _inject_custom_sidenav(items, selected_key)

    # Rendu de la vue sélectionnée
    if selected_key == "Global":
        if pre_global_fn is not None:
            pre_global_fn()
        render_global_overview()
        render_global_live_prices()
        if global_fn is not None:
            global_fn()
    else:
        idx = keys.index(selected_key) - 1
        render_fn(assets[idx])



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

    # ── Section : Sources de données (Q11/Q12) ───────────────────────────────
    with st.expander("🔑 **Sources de données**", expanded=False):
        st.caption("Fournisseur de données de marché. La clé API est stockée dans `config/secrets.yaml` (gitignored).")

        try:
            from quant.config import get_twelve_data_key
            current_key = get_twelve_data_key()
        except Exception:
            current_key = ""

        try:
            from utils.config import load_settings
            _s = load_settings()
            current_provider = _s.get("data", {}).get("provider", "auto")
        except Exception:
            current_provider = "auto"

        provider_opts = ["auto", "twelve_data", "yahoo"]
        provider = st.selectbox(
            "Fournisseur de données",
            options=provider_opts,
            index=provider_opts.index(current_provider) if current_provider in provider_opts else 0,
            key="data_provider_select",
            help="auto = Twelve Data si clé disponible, sinon Yahoo Finance.",
        )
        api_key_input = st.text_input(
            "Clé API Twelve Data",
            value=current_key,
            type="password",
            key="twelve_data_api_key",
            help="Clé API Twelve Data (https://twelvedata.com). Stockée dans config/secrets.yaml (gitignored).",
        )

        if st.button("💾 Sauvegarder les sources de données", key="btn_save_data_sources"):
            try:
                from pathlib import Path
                import yaml as _yaml

                # Sauvegarder la clé dans secrets.yaml (gitignored)
                secrets_path = Path(__file__).resolve().parent.parent / "config" / "secrets.yaml"
                secrets_content = {"data": {"twelve_data_key": api_key_input.strip()}}
                with secrets_path.open("w", encoding="utf-8") as fh:
                    _yaml.dump(secrets_content, fh, allow_unicode=True, default_flow_style=False)

                # Sauvegarder le provider dans settings.yaml
                from utils.config import load_settings, save_settings
                settings = load_settings()
                settings.setdefault("data", {})["provider"] = provider
                save_settings(settings)

                st.success("✅ Sources de données sauvegardées (clé dans `config/secrets.yaml`).")
            except Exception as exc:
                st.error(f"Erreur sauvegarde : {exc}")

    st.markdown("---")

    # ── Section : Paramètres quant globaux (Q3/Q13/Q14/Q17) ─────────────────
    with st.expander("⚙️ **Paramètres quant globaux**", expanded=False):
        st.caption("Paramètres globaux du pipeline quant. Sauvegardés dans `settings.yaml → quant:`.")

        try:
            from quant.config import get_quant_cfg, save_quant_cfg
            qcfg = get_quant_cfg()
        except Exception as exc:
            st.error(f"QuantConfig non chargé : {exc}")
            qcfg = None

        if qcfg is not None:
            st.markdown("**Horizon de prédiction**")
            q_horizon = st.slider(
                "Horizon (barres forward)",
                min_value=1, max_value=48,
                value=int(qcfg.horizon_bars),
                key="qcfg_horizon_bars",
                help="Nombre de barres futures à prédire (ex. 4 = prédiction à 4×timeframe).",
            )

            # Horizon sweep (Q3)
            st.markdown("**Sweep d'horizons (Q3)**")
            sweep_raw = qcfg.horizon_sweep_values
            if isinstance(sweep_raw, list):
                sweep_default = sweep_raw
            elif isinstance(sweep_raw, str):
                sweep_default = [int(v.strip()) for v in sweep_raw.split(",") if v.strip()]
            else:
                sweep_default = [2, 4, 8, 12]
            sweep_opts = list(range(1, 49))
            q_sweep = st.multiselect(
                "Horizons à tester en sweep",
                options=sweep_opts,
                default=[v for v in sweep_default if v in sweep_opts],
                key="qcfg_horizon_sweep",
                help="Horizons (en barres) testés lors de sweep_horizon(). Choisir 3-6 valeurs.",
            )

            st.markdown("**Feature DXY (Q14)**")
            q_dxy = st.toggle(
                "Utiliser le DXY comme feature inter-marché",
                value=bool(qcfg.use_dxy_feature),
                key="qcfg_use_dxy",
                help="Active la feature US Dollar Index dans le modèle (pertinent pour XAU, EUR, GBP, WTI).",
            )

            st.markdown("**Refit adaptatif KS-test (Q17)**")
            trigger_opts = ["schedule", "ks_test", "both"]
            trigger_labels = {
                "schedule": "Planifié (toujours refitter)",
                "ks_test": "KS-test uniquement (drift détecté)",
                "both": "Les deux (planifié + drift)",
            }
            q_trigger = st.selectbox(
                "Déclencheur de refit",
                options=trigger_opts,
                index=trigger_opts.index(qcfg.refit_trigger) if qcfg.refit_trigger in trigger_opts else 0,
                format_func=lambda x: trigger_labels[x],
                key="qcfg_refit_trigger",
                help="Quand refitter le modèle. 'ks_test' évite les refits inutiles si la distribution n'a pas changé.",
            )
            c_ks1, c_ks2 = st.columns(2)
            with c_ks1:
                q_ks_threshold = st.number_input(
                    "Seuil p-value KS",
                    min_value=0.01, max_value=0.20, step=0.01,
                    value=float(qcfg.refit_ks_pvalue_threshold),
                    key="qcfg_ks_threshold",
                    help="p-value en dessous de laquelle un drift est détecté (refit déclenché).",
                )
            with c_ks2:
                q_ks_window = st.number_input(
                    "Fenêtre KS (jours)",
                    min_value=3, max_value=60, step=1,
                    value=int(qcfg.refit_ks_window_days),
                    key="qcfg_ks_window",
                    help="Nombre de jours de données récentes comparés à la distribution de référence.",
                )

            if st.button("💾 Sauvegarder les paramètres quant", key="btn_save_qcfg"):
                try:
                    from dataclasses import replace as _dc_replace
                    updated = _dc_replace(
                        qcfg,
                        horizon_bars=int(q_horizon),
                        horizon_sweep_values=sorted(q_sweep) if q_sweep else [2, 4, 8, 12],
                        use_dxy_feature=bool(q_dxy),
                        refit_trigger=q_trigger,
                        refit_ks_pvalue_threshold=float(q_ks_threshold),
                        refit_ks_window_days=int(q_ks_window),
                    )
                    save_quant_cfg(updated)
                    st.success("✅ Paramètres quant sauvegardés dans `settings.yaml`.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Erreur sauvegarde quant : {exc}")

    st.markdown("---")

    # ── Gestion des actifs actifs ─────────────────────────────────────────────
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
    all_known = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XAU/USD", "XAG/USD", "WTI/USD", "EUR/USD", "GBP/USD"]
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


def _load_raw_asset_yaml(asset: str) -> dict:
    """Charge uniquement le fichier assets/{slug}.yaml sans merge global."""
    from pathlib import Path
    import yaml
    slug = asset.replace("/", "_")
    p = Path(__file__).resolve().parent.parent / "config" / "assets" / f"{slug}.yaml"
    if not p.exists():
        return {"asset": asset}
    raw = p.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    return yaml.safe_load(text) or {"asset": asset}


def _render_asset_config_editor(
    asset: str,
    load_fn: Callable,
    save_fn: Callable,
) -> None:
    """Formulaire d'édition de la config V2 d'un actif (v2_risk + circuit_breaker)."""
    import streamlit as st

    icon = _asset_icon(asset)
    slug = asset.replace("/", "_")

    with st.expander(f"{icon} **{asset}**", expanded=False):
        try:
            # Charger la config fusionnée (globale + asset) pour afficher les vraies valeurs
            cfg = load_fn(asset)
        except Exception as exc:
            st.warning(f"Config {asset} non chargée : {exc}")
            return

        v2r = cfg.get("v2_risk", {})
        cb  = cfg.get("circuit_breaker", {})

        # ── Timeframe par actif (Q1/Q15) ──────────────────────────────────────
        tf_opts = ["1m", "5m", "15m", "1h", "4h"]
        current_tf = str(cfg.get("timeframe", "15m"))
        tf_idx = tf_opts.index(current_tf) if current_tf in tf_opts else 2  # défaut 15m
        asset_timeframe = st.selectbox(
            "⏱️ Timeframe",
            options=tf_opts,
            index=tf_idx,
            key=f"tf_{slug}",
            help="Granularité OHLCV pour cet actif. Crypto: 5m recommandé. Forex/Commodités: 15m.",
        )

        # ── Capital ──────────────────────────────────────────────────────────
        paper_cap = st.number_input(
            "💰 Capital paper (USD)",
            min_value=500, max_value=1_000_000, step=500,
            value=int(cfg.get("paper_capital_usd", 10_000)),
            key=f"paper_cap_{slug}",
            help="Montant alloué à cet actif en mode paper trading.",
        )

        # ── v2_risk — mode tendance ───────────────────────────────────────
        st.caption("Paramètres risque V2 — mode TREND")
        c1, c2, c3 = st.columns(3)
        with c1:
            sl_mult = st.number_input(
                "SL ATR ×", min_value=0.5, max_value=10.0, step=0.25,
                value=float(v2r.get("stop_loss_atr_mult", 2.5)),
                key=f"sl_{slug}",
                help="Multiplicateur ATR pour le Stop-Loss (ex : 2.5 = SL à 2.5×ATR)",
            )
        with c2:
            tp_mult = st.number_input(
                "TP ATR ×", min_value=0.5, max_value=15.0, step=0.25,
                value=float(v2r.get("take_profit_atr_mult", 3.5)),
                key=f"tp_{slug}",
                help="Multiplicateur ATR pour le Take-Profit",
            )
        with c3:
            frac = st.number_input(
                "Fraction / trade (%)", min_value=0.05, max_value=5.0, step=0.05,
                value=round(float(v2r.get("fraction_per_trade", 0.0075)) * 100, 4),
                key=f"frac_{slug}",
                format="%.3f",
                help="Fraction du capital risquée par trade (ex : 0.750 = 0.75%)",
            )

        c4, c5 = st.columns(2)
        with c4:
            max_dd = st.number_input(
                "Max drawdown (%)", min_value=1.0, max_value=50.0, step=0.5,
                value=float(v2r.get("max_drawdown_pct", 15.0)),
                key=f"maxdd_{slug}",
                help="Kill-switch hebdomadaire si le drawdown dépasse ce seuil",
            )

        # ── v2_risk — mode RANGE ─────────────────────────────────────────
        st.caption("Paramètres risque V2 — mode RANGE (mean-revert)")
        r1, r2, r3 = st.columns(3)
        with r1:
            rsl = st.number_input(
                "SL range ATR ×", min_value=0.5, max_value=5.0, step=0.25,
                value=float(v2r.get("range_sl_atr_mult", 1.5)),
                key=f"rsl_{slug}",
            )
        with r2:
            rtp = st.number_input(
                "TP range ATR ×", min_value=0.5, max_value=5.0, step=0.25,
                value=float(v2r.get("range_tp_atr_mult", 1.5)),
                key=f"rtp_{slug}",
            )
        with r3:
            rfm = st.number_input(
                "Fraction mult range", min_value=0.1, max_value=1.0, step=0.05,
                value=float(v2r.get("range_fraction_mult", 0.50)),
                key=f"rfm_{slug}",
                help="Multiplicateur du sizing en mode RANGE (< 1 = positions plus petites)",
            )

        # ── Circuit-breaker ──────────────────────────────────────────────
        st.caption("Circuit-breaker funding rate (crypto uniquement)")
        cb1, cb2 = st.columns(2)
        with cb1:
            fw = st.number_input(
                "Funding warning", min_value=0.0, max_value=0.002, step=0.00001,
                value=float(cb.get("funding_warning", 0.00018)),
                key=f"fw_{slug}", format="%.5f",
                help="Seuil de réduction du sizing (taux de funding annualisé)",
            )
        with cb2:
            fb = st.number_input(
                "Funding block", min_value=0.0, max_value=0.005, step=0.00001,
                value=float(cb.get("funding_block", 0.00045)),
                key=f"fb_{slug}", format="%.5f",
                help="Seuil de blocage total des entrées",
            )

        if st.button(f"💾 Sauvegarder {asset}", key=f"save_{slug}"):
            # Ne sauvegarder que les champs propres à l'actif (pas les globaux du merge)
            asset_overrides: dict = {
                "asset": asset,
                "timeframe": asset_timeframe,
                "paper_capital_usd": int(paper_cap),
            }
            asset_overrides["v2_risk"] = {
                "stop_loss_atr_mult":    round(sl_mult, 4),
                "take_profit_atr_mult":  round(tp_mult, 4),
                "fraction_per_trade":    round(frac / 100, 6),
                "max_drawdown_pct":      round(max_dd, 2),
                "range_sl_atr_mult":     round(rsl, 4),
                "range_tp_atr_mult":     round(rtp, 4),
                "range_fraction_mult":   round(rfm, 4),
            }
            asset_overrides["circuit_breaker"] = {
                **cfg.get("circuit_breaker", {}),
                "funding_warning": round(fw, 6),
                "funding_block":   round(fb, 6),
            }
            try:
                save_fn(asset, asset_overrides)
                st.success(f"✅ Config {asset} sauvegardée.")
            except Exception as exc:
                st.error(f"Erreur : {exc}")
