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

import streamlit as st
from utils.i18n import t

# ── API URL (Docker = atlas-v4-api, local = host.docker.internal) ──────────
import os as _os
_API_BASE = _os.environ.get("V4_API_URL", "http://host.docker.internal:8000")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _active_assets() -> list[str]:
    """Retourne les actifs des DAGs actifs. Fallback config si API injoignable."""
    # 1) Actifs des DAGs actifs (prioritaire)
    try:
        import urllib.request, json
        req = urllib.request.Request(f"{_API_BASE}/dag/status", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            dags = json.loads(resp.read())
        assets = [d.get("asset", "") for d in dags if d.get("asset")]
        if assets:
            return assets
    except Exception:
        pass

    # 2) Fallback: carry_assets.yaml (via v7.core.asset_config)
    try:
        from v7.core.asset_config import get_active_assets as _cfg_active
        assets = _cfg_active()
        if assets:
            return assets
    except Exception:
        return ["BTC/USDT"]


def _asset_icon(asset: str) -> str:
    """Picto de l'actif : logo local (upload) > logo git (images/assets/) > cercle coloré fallback."""
    from pathlib import Path as _IPath
    import base64 as _b64

    ticker = asset.split("/")[0]

    # 1) Logo uploadé dans /app/data/logos/ (icon_url dans la config)
    try:
        from v7.core.asset_config import get_asset_params
        params = get_asset_params(asset)
        logo_file = params.get("icon_url", "")
        if logo_file:
            logo_path = _IPath("/app/data/logos") / logo_file
            if logo_path.exists():
                return _img_b64(logo_path)
    except Exception:
        pass

    # 2) Logo git-tracked dans images/assets/{TICKER}.svg
    for ext in (".svg", ".png", ".webp", ".jpg"):
        git_path = _IPath("/app/src/images/assets") / f"{ticker}{ext}"
        if git_path.exists():
            return _img_b64(git_path)

    # 3) Fallback cercle coloré
    return _fallback_icon_html(asset)


def _img_b64(path) -> str:
    """Encode une image en data URI base64."""
    import base64 as _b64
    ext = path.suffix.lower()
    mime = "image/svg+xml" if ext == ".svg" else ("image/webp" if ext == ".webp" else "image/png")
    data = _b64.b64encode(path.read_bytes()).decode()
    return (f'<img src="data:{mime};base64,{data}" width="16" height="16" '
            f'style="vertical-align:middle;border-radius:50%;">')


def _fallback_icon_html(asset: str) -> str:
    """Cercle coloré avec les initiales du token."""
    ticker = asset.split("/")[0]
    initial = ticker[:2].upper() if len(ticker) > 1 else ticker[0].upper()
    hue = (sum(ord(c) * (i + 1) for i, c in enumerate(ticker)) * 37) % 360
    return (f'<span style="display:inline-block;width:16px;height:16px;'
            f'background:hsl({hue},55%,45%);color:#fff;border-radius:50%;'
            f'text-align:center;line-height:16px;font-size:7px;'
            f'font-weight:700;vertical-align:middle;">{initial}</span>')


def _action_badge(action: str) -> str:
    colors = {"BUY": "#27ae60", "SELL": "#e74c3c", "HOLD": "#888888"}
    color = colors.get(action, "#888888")
    return f'<span style="background:{color};color:#fff;border-radius:3px;padding:1px 7px;font-size:12px;">{action}</span>'


def _score_bar(score: float, theme: str = "dark") -> str:
    """Mini barre de progression HTML pour le score."""
    color = "#27ae60" if score >= 60 else ("#e74c3c" if score < 40 else "#f39c12")
    track = "#e0e0e0" if theme == "light" else "#333"
    return (
        f'<div style="display:flex;align-items:center;gap:6px;">'
        f'<div style="width:80px;height:8px;background:{track};border-radius:4px;overflow:hidden;">'
        f'<div style="width:{score:.0f}%;height:100%;background:{color};border-radius:4px;"></div>'
        f'</div>'
        f'<span style="font-size:13px;">{score:.0f}</span>'
        f'</div>'
    )


# ---------------------------------------------------------------------------
# Composant 1 : Vue globale (données live des DAGs actifs)
# ---------------------------------------------------------------------------

_ACTION_TO_DIR = {"long": 75, "short": 25, "flat": 50, "hold": 50}

@st.cache_data(ttl=30)
def _fetch_v4_dags() -> list[dict]:
    """Récupère le statut de tous les DAGs V4."""
    try:
        import urllib.request, json
        req = urllib.request.Request(f"{_API_BASE}/dag/status")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception:
        return []


def render_global_overview() -> None:
    """
    Tableau consolidé multi-actifs — données V4 live.
    Affiche l'état de chaque DAG actif : signal, tendance, dernier trade, statut.
    """
    import streamlit as st

    dags = _fetch_v4_dags()
    if not dags:
        # Fallback V3 silencieux — ne rien afficher plutôt que des données obsolètes
        return

    theme = st.query_params.get("theme", "dark")

    html_rows = ""
    for d in dags:
        dag_id = d.get("dag_id", "?")
        asset = d.get("asset", "?")
        running = d.get("running", False)
        last_ts = d.get("last_run_at")
        results = d.get("last_results", {})

        ts_str = ""
        if last_ts:
            from datetime import datetime as _dt
            try:
                ts_str = _dt.fromtimestamp(last_ts).strftime("%H:%M:%S")
            except Exception:
                ts_str = "—"
        else:
            ts_str = "—"

        icon = _asset_icon(asset) if asset else "◈"
        pfx = asset.split("/")[0].lower()[:3] if asset else "btc"
        is_v7 = dag_id.startswith("v7_")

        if is_v7:
            # ── V7: Funding Carry ──
            carry_node = results.get(f"{pfx}_carry", {})
            carry_out = carry_node.get("outputs", {}) if isinstance(carry_node, dict) else {}
            carry_signal = carry_out.get("signal", "flat")
            funding_rate = carry_out.get("funding_rate", 0)
            annual_pct = carry_out.get("annual_funding_pct", 0)
            size_usd = carry_out.get("size_usd", 0)
            position_open = carry_out.get("position_open", False)

            # ── LLM AI Analyst (affiché dans la section "🧠 Dernières analyses IA", pas dans ce tableau) ──
            # Le cache LLM est consulté uniquement par la section dédiée.

            score = int(50 + annual_pct * 3) if annual_pct > 0 else 50
            score = min(95, max(5, score))  # 5-95 au lieu de 0-100

            # Trade info : distinguer nouvelle ouverture vs position active
            total_received = carry_out.get("total_funding_received", 0)
            n_payments = carry_out.get("n_payments", 0)
            if carry_signal == "open_carry":
                trade_str = f"🟢 CARRY ${size_usd:,.0f}"
            elif position_open and total_received > 0:
                trade_str = f"💰 +${total_received:.4f} ({n_payments}×)"
            elif position_open:
                trade_str = "🟢 CARRY actif"
            elif funding_rate > 0:
                trade_str = f"funding {funding_rate*100:.4f}%"
            else:
                trade_str = f"funding {funding_rate*100:.4f}%"

            trend = f"{annual_pct:+.1f}%/an" if annual_pct != 0 else "—"
            signal_display = "💸 carry" if carry_signal.startswith("open") else ("📥 collecte" if position_open else f"💸 {carry_signal}")
        else:
            # ── V5/V6 Legacy ──
            signal_node = results.get(f"{pfx}_signal", {}) or results.get("signal", {})
            trend_node = results.get(f"{pfx}_trend", {})
            risk_node = results.get(f"{pfx}_risk", {})
            short_risk = results.get(f"{pfx}_short_risk", {})
            paper_node = results.get(f"{pfx}_paper", {})

            signal_out = signal_node.get("outputs", {}) if isinstance(signal_node, dict) else {}
            trend_out = trend_node.get("outputs", {}) if isinstance(trend_node, dict) else {}
            risk_out = risk_node.get("outputs", {}) if isinstance(risk_node, dict) else {}
            short_out = short_risk.get("outputs", {}) if isinstance(short_risk, dict) else {}
            paper_out = paper_node.get("outputs", {}) if isinstance(paper_node, dict) else {}

            signal = signal_out.get("signal", "—")
            prob_up = signal_out.get("prob_up")
            trend = trend_out.get("trend", "—")
            risk_decision = risk_out.get("decision", {})
            short_decision = short_out.get("decision", {})
            trade_result = paper_out.get("trade_result", {})

            if isinstance(risk_decision, str):
                risk_decision = {}
            if isinstance(short_decision, str):
                short_decision = {}
            if isinstance(trade_result, str):
                trade_result = {}

            # Score = prob_up × 100 ou 50 si flat
            if signal == "long":
                score = int((prob_up or 0.75) * 100)
            elif signal == "short":
                score = int(((1 - (prob_up or 0.5)) * 100))
            else:
                score = 50
            signal_display = signal

            # Trade info
            trade_action = risk_decision.get("action") or short_decision.get("action")
            trade_price = risk_decision.get("entry_price") or short_decision.get("entry_price")
            if trade_action and trade_action != "flat" and trade_price:
                trade_str = f'{trade_action.upper()} @ ${trade_price:,.0f}'
            elif trade_action == "flat" or not trade_action:
                trade_str = "—"
            else:
                trade_str = str(trade_action or "—")

        # Statut du DAG
        status_icon = "🟢" if running else "⚫"
        status_text = "actif" if running else "arrêté"

        html_rows += (
            f"<tr>"
            f"<td style='padding:6px 10px;'>{icon} {asset}</td>"
            f"<td style='padding:6px 10px;'>{_action_badge(signal_display)}</td>"
            f"<td style='padding:6px 10px;'>{_score_bar(score, theme)}</td>"
            f"<td style='padding:6px 10px;font-size:12px;opacity:.7;'>{ts_str}</td>"
            f"<td style='padding:6px 10px;font-size:12px;'>{trade_str}</td>"
            f"<td style='padding:6px 10px;font-size:12px;'>{trend if trend else '—'}</td>"
            f"<td style='padding:6px 10px;font-size:12px;'>{status_icon} {status_text}</td>"
            f"</tr>"
        )

    st.markdown(f"### 🌐 {t('global_view_title')}")
    st.markdown(
        f"""<table style="width:100%;border-collapse:collapse;">
        <thead><tr style="border-bottom:1px solid {'#dee2e6' if theme == 'light' else '#444'};font-size:11px;opacity:.6;">
          <th style="padding:4px 8px;text-align:left;">{t('col_asset')}</th>
          <th style="padding:4px 8px;text-align:left;">{t('col_signal')}</th>
          <th style="padding:4px 8px;text-align:left;">{t('col_score')}</th>
          <th style="padding:4px 8px;text-align:left;">{t('col_run')}</th>
          <th style="padding:4px 8px;text-align:left;">{t('col_carry')}</th>
          <th style="padding:4px 8px;text-align:left;">{t('col_return')}</th>
          <th style="padding:4px 8px;text-align:left;">{t('col_status')}</th>
        </tr></thead>
        <tbody>{html_rows}</tbody>
        </table>""",
        unsafe_allow_html=True,
    )
    st.markdown("---")


# ---------------------------------------------------------------------------
# Composant 1b : Prix live multi-actifs (cartes) — V4 API
# ---------------------------------------------------------------------------

@st.cache_data(ttl=15)
def _fetch_v4_prices() -> dict[str, dict]:
    """Récupère les prix live depuis l'API V4 (WebSocket Binance)."""
    try:
        import urllib.request, json
        req = urllib.request.Request(f"{_API_BASE}/prices/snapshot")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read())
    except Exception:
        return {}


def render_global_live_prices() -> None:
    """Grille de prix live — polling AJAX toutes les 3s, pas de refresh page."""
    import streamlit as st
    import json as _json

    dags = _fetch_v4_dags()
    if not dags:
        return
    dag_assets = list({d.get("asset", "") for d in dags if d.get("asset")})
    if not dag_assets:
        dag_assets = ["BTC/USDT"]

    prices = _fetch_v4_prices()

    st.markdown(f"### 📡 {t('live_price_title')}")

    # Construire les cartes HTML avec data-attrs pour le JS
    cards = ""
    pos_data = {}  # sym → {action, entry, size}
    for asset in dag_assets:
        icon = _asset_icon(asset)
        pdata = prices.get(asset, {})
        price = pdata.get("price")
        price_str = _fmt_price(price)
        init_price = price or 0

        dag = next((d for d in dags if d.get("asset") == asset), None)
        trend_label = sig_label = pos_html = "—"
        if dag:
            pfx = asset.split("/")[0].lower()[:3]
            results = dag.get("last_results", {})
            tn = results.get(f"{pfx}_trend", {})
            trend = tn.get("outputs", {}).get("trend", "") if isinstance(tn, dict) else ""
            sn = results.get(f"{pfx}_signal", {})
            signal = sn.get("outputs", {}).get("signal", "") if isinstance(sn, dict) else ""
            prob = sn.get("outputs", {}).get("prob_up") if isinstance(sn, dict) else None
            trend_label = trend.upper() if trend else "—"
            sig_label = f"{signal} {prob*100:.0f}%" if signal and prob is not None else "—"

            # Position ouverte ?
            pm = results.get(f"{pfx}_posmgr", {})
            open_pos = pm.get("outputs", {}).get("open_positions", []) if isinstance(pm, dict) else []
            if isinstance(open_pos, list) and open_pos:
                p0 = open_pos[0] if isinstance(open_pos[0], dict) else {}
                p_action = p0.get("action", "")
                p_entry = p0.get("entry_price", 0)
                p_size = p0.get("size_usd", 0)
                pos_data[asset] = {"action": p_action, "entry": p_entry, "size": p_size}
                # PnL latent initial
                if p_entry and price:
                    if p_action == "short":
                        pnl_pct = (p_entry - price) / p_entry * 100
                    else:
                        pnl_pct = (price - p_entry) / p_entry * 100
                    pnl_col = "#2ecc71" if pnl_pct >= 0 else "#e74c3c"
                    pos_html = f'<span style="color:{pnl_col}">{p_action.upper()} {pnl_pct:+.1f}%</span>'
                else:
                    pos_html = p_action.upper()

        uid = asset.replace("/", "_")
        cards += (
            f'<div class="px-card" id="card_{uid}" data-init="{init_price}"'
            f' style="display:inline-block;text-align:center;'
            f'padding:10px 16px;margin:4px;border-radius:10px;min-width:140px;'
            f'border:1px solid rgba(255,255,255,0.08);">'
            f'<div style="font-size:18px;">{icon}</div>'
            f'<div style="font-size:11px;opacity:0.6;">{asset}</div>'
            f'<div class="px-price" id="px_{uid}" style="font-size:22px;font-weight:700;'
            f'font-variant-numeric:tabular-nums;">{price_str}</div>'
            f'<div class="px-chg" id="chg_{uid}" style="font-size:11px;margin:2px 0;">—</div>'
            f'<div class="px-pos" id="pos_{uid}" style="font-size:10px;opacity:0.7;">{pos_html}</div>'
            f'<div style="font-size:9px;opacity:0.45;">{trend_label} | {sig_label}</div>'
            f'</div>'
        )

    symbols_js = _json.dumps(dag_assets)
    pos_data_js = _json.dumps(pos_data)
    
    # Hauteur dynamique : ~4.5 cartes par ligne, ~90px par ligne, minimum 200px
    cards_per_row = 4.5
    row_h = 90
    n_assets = len(dag_assets)
    dyn_height = max(200, int((n_assets / cards_per_row + 0.5) * row_h))

    st.components.v1.html(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
body{{margin:0;padding:6px;font-family:system-ui,sans-serif;background:transparent;color:#e6edf3;}}
.px-card{{transition:background .3s;}}
.px-card.up{{background:rgba(46,204,113,.12)!important;}}
.px-card.dn{{background:rgba(231,76,60,.12)!important;}}
</style></head><body>
<div style="display:flex;flex-wrap:wrap;justify-content:center;gap:6px;">
{cards}
</div>
<script>
var SYMBOLS={symbols_js};
var POSDATA={pos_data_js};
var LAST={{}}, FIRST={{}};
function apiUrl(){{
  try{{
    var p=window.top.location.protocol;
    var h=window.top.location.hostname;
    if(p==='https:')return p+'//'+h+'/api';
    if(h)return'http://'+h+':8000';
  }}catch(e){{}}
  return'http://192.168.1.80:8000';
}}
function fmt(p){{
  if(p==null)return'—';
  if(p>=1000)return'$'+p.toLocaleString('en-US',{{maximumFractionDigits:0}});
  if(p>=1)return'$'+p.toLocaleString('en-US',{{minimumFractionDigits:2,maximumFractionDigits:2}});
  return'$'+p.toLocaleString('en-US',{{minimumFractionDigits:4,maximumFractionDigits:4}});
}}
function fmtPct(v){{return(v>=0?'+':'')+v.toFixed(2)+'%';}}
function poll(){{
  fetch(apiUrl()+'/prices/snapshot').then(function(r){{return r.json()}}).then(function(data){{
    SYMBOLS.forEach(function(sym){{
      var obj=data[sym];if(!obj)return;
      var p=(typeof obj==='object')?obj.price:obj;
      if(!p)return;
      var uid=sym.replace(/\\//g,'_');
      var el=document.getElementById('px_'+uid);
      var chgEl=document.getElementById('chg_'+uid);
      var posEl=document.getElementById('pos_'+uid);
      var card=document.getElementById('card_'+uid);
      if(!el)return;

      // Variation %
      var first=FIRST[sym];
      if(!first){{first=p;FIRST[sym]=p;}}
      var chgPct=(p-first)/first*100;
      var arrow=chgPct>0.05?'▲':(chgPct<-0.05?'▼':'◆');
      var chgCol=chgPct>0.05?'#2ecc71':(chgPct<-0.05?'#e74c3c':'#888');
      if(chgEl)chgEl.innerHTML='<span style="color:'+chgCol+'">'+arrow+' '+fmtPct(chgPct)+'</span>';

      // Flash
      var old=LAST[sym];
      if(old&&p>old){{card.classList.add('up');setTimeout(function(){{card.classList.remove('up')}},400);}}
      if(old&&p<old){{card.classList.add('dn');setTimeout(function(){{card.classList.remove('dn')}},400);}}
      LAST[sym]=p;
      el.textContent=fmt(p);

      // Position PnL latent
      var pos=POSDATA[sym];
      if(pos&&posEl){{
        var pnlPct=pos.action==='short'?(pos.entry-p)/pos.entry*100:(p-pos.entry)/pos.entry*100;
        var col=pnlPct>=0?'#2ecc71':'#e74c3c';
        posEl.innerHTML='<span style="color:'+col+'">'+pos.action.toUpperCase()+' '+((pnlPct>=0)?'+':'')+pnlPct.toFixed(1)+'%</span>';
      }}
    }});
  }}).catch(function(){{}});
}}
setInterval(poll,3000);
poll();
</script>
</body></html>""", height=dyn_height, scrolling=False)





def _fmt_price(price: float | None) -> str:
    """Formate un prix pour affichage."""
    if price is None:
        return "—"
    if price >= 1000:
        return f"${price:,.0f}"
    if price >= 1:
        return f"${price:,.2f}"
    return f"${price:.4f}"


# ---------------------------------------------------------------------------
# Composant 2 : Onglets par actif
# ---------------------------------------------------------------------------

def _inject_custom_sidenav(items: list, active_key: str, qparam: str = "_asset", theme: str = "dark") -> None:
    """Injecte une sidebar fixe dans le document parent (indépendante de st.sidebar).
    items  : liste de dicts {key, icon, text}
    active_key : clé de l'item actif
    qparam : nom du query parameter utilisé pour la navigation
    """
    import json as _json
    import streamlit.components.v1 as _cv1

    items_js    = _json.dumps(items)
    active_js   = _json.dumps(active_key)
    qparam_js   = _json.dumps(qparam)
    is_light_js = "true" if theme == "light" else "false"

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

  /* CSS — mis à jour à chaque rendu pour refléter le thème courant */
  var IS_LIGHT = {is_light_js};
  var NAV_BG     = IS_LIGHT ? '#f0f2f6'           : '#161b22';
  var NAV_BDR    = IS_LIGHT ? 'rgba(0,0,0,.12)'   : 'rgba(255,255,255,.12)';
  var ANT_BDR    = IS_LIGHT ? 'rgba(0,0,0,.08)'   : 'rgba(255,255,255,.07)';
  var ANT_FG     = IS_LIGHT ? 'rgba(0,0,0,.4)'    : 'rgba(255,255,255,.5)';
  var ANS_FG     = IS_LIGHT ? '#555'              : '#fff';
  var ANI_FG     = IS_LIGHT ? 'rgba(0,0,0,.65)'   : 'rgba(255,255,255,.75)';
  var ANI_HOV    = IS_LIGHT ? 'rgba(0,0,0,.06)'   : 'rgba(255,255,255,.08)';
  var ANI_HOV_FG = IS_LIGHT ? 'rgba(0,0,0,.85)'   : '#fff';
  var ANI_A_BG   = IS_LIGHT ? 'rgba(255,75,75,.15)' : 'rgba(255,75,75,.22)';
  var ANI_A_FG   = IS_LIGHT ? '#c0392b'           : '#fff';
  var navCss =
    '#atlas-sidenav{{position:fixed;left:0;' +
    'width:' + W + 'px;background:' + NAV_BG + ';z-index:100;' +
    'display:flex;flex-direction:column;' +
    'border-right:1px solid ' + NAV_BDR + ';' +
    'transition:width .2s ease;overflow:hidden;box-sizing:border-box;}}' +
    '#atlas-sidenav.c{{width:' + MINI + 'px;}}' +
    '#atlas-sidenav-scroll{{flex:1;overflow-y:auto;overflow-x:hidden;}}' +
    '#ant{{display:flex;align-items:center;justify-content:flex-end;height:34px;' +
    'padding:0 10px;cursor:pointer;border-bottom:1px solid ' + ANT_BDR + ';' +
    'color:' + ANT_FG + ';font-size:17px;user-select:none;flex-shrink:0;}}' +
    '#atlas-sidenav.c #ant{{justify-content:center;padding:0;}}' +
    '.ans{{font-size:8px;font-weight:700;letter-spacing:1.5px;opacity:.35;' +
    'text-transform:uppercase;padding:6px 12px 1px;color:' + ANS_FG + ';white-space:nowrap;flex-shrink:0;}}' +
    '#atlas-sidenav.c .ans{{display:none;}}' +
    '.ani{{display:flex;align-items:center;gap:7px;padding:4px 8px;text-decoration:none;' +
    'color:' + ANI_FG + ';font-size:12px;' +
    'font-family:-apple-system,BlinkMacSystemFont,sans-serif;' +
    'border-radius:5px;margin:0 4px;white-space:nowrap;transition:background .15s;}}' +
    '#atlas-sidenav.c .ani{{justify-content:center;padding:6px 0;margin:0;border-radius:0;}}' +
    '.ani:hover{{background:' + ANI_HOV + ';color:' + ANI_HOV_FG + ';}}' +
    '.ani.a{{background:' + ANI_A_BG + ';font-weight:600;color:' + ANI_A_FG + ';}}' +
    '.ani-ic{{font-size:17px;min-width:24px;text-align:center;flex-shrink:0;line-height:1;}}' +
    '#atlas-sidenav.c .ani-ic{{min-width:' + MINI + 'px;font-size:15px;}}' +
    '.ani-tx{{white-space:nowrap;overflow:hidden;transition:opacity .15s;}}' +
    '#atlas-sidenav.c .ani-tx{{opacity:0;width:0;pointer-events:none;position:absolute;}}';
  var navCssEl = d.getElementById('atlas-nav-css');
  if (!navCssEl) {{ navCssEl = d.createElement('style'); navCssEl.id = 'atlas-nav-css'; d.head.appendChild(navCssEl); }}
  navCssEl.textContent = navCss;

  /* Construction du nav */
  var existing = d.getElementById('atlas-sidenav');
  var wasC = existing ? existing.classList.contains('c') : collapsed;
  var nav = d.createElement('div');
  nav.id = 'atlas-sidenav';
  if (wasC) nav.classList.add('c');

  nav.innerHTML =
    '<div id="ant" title="Réduire / Agrandir">&#9776;</div>' +
    '<div id="atlas-sidenav-scroll">' +
    ITEMS.map(function(it) {{
      if (it.section) {{
        return '<div class="ans">' + it.section + '</div>';
      }}
      var cls = 'ani' + (it.key === ACTIVE ? ' a' : '');
      return '<a class="' + cls + '" href="' + navUrl(it.key) + '" title="' + it.text + '">' +
             '<span class="ani-ic">' + it.icon + '</span>' +
             '<span class="ani-tx">' + it.text + '</span></a>';
    }}).join('') + '</div>';

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

    _inject_custom_sidenav(items, selected_key, theme=st.query_params.get("theme", "dark"))

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

    # ── Section : Sources de données ───────────────────────────────────────────
    with st.expander("🔑 " + t("data_sources_title"), expanded=False):
        st.caption(t("data_provider_config"))

        try:
            from pathlib import Path as _MAPath
            import yaml as _MAYaml
            _ma_secrets = _MAPath(__file__).resolve().parent.parent / "config" / "secrets.yaml"
            _ma_cfg = _MAYaml.safe_load(_ma_secrets.read_text(encoding="utf-8")) or {} if _ma_secrets.exists() else {}
            current_key = _ma_cfg.get("data", {}).get("twelve_data_key", "")
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
            t("data_provider_label"),
            options=provider_opts,
            index=provider_opts.index(current_provider) if current_provider in provider_opts else 0,
            key="data_provider_select",
            help=t("ma_provider_help"),
        )
        api_key_input = st.text_input(
            t("ma_td_api_key_label"),
            value=current_key,
            type="password",
            key="twelve_data_api_key",
            help=t("ma_td_api_key_help"),
        )

        if st.button(t("cfg_save_data_sources"), key="btn_save_data_sources"):
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

                st.success(t("ma_td_saved"))
            except Exception as exc:
                st.error(f"{t('cfg_save_data_sources')} — {exc}")

    st.markdown("---")

    # ── Section : Paramètres quant globaux (Q3/Q13/Q14/Q17) ───────────────────
    with st.expander(t("cfg_section_quant"), expanded=False):
        st.caption(t("cfg_section_quant_caption"))

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

            if st.button(t("cfg_save_quant"), key="btn_save_qcfg"):
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
                    st.success(t("cfg_quant_saved"))
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
    st.markdown(t("cfg_active_assets_label"))
    all_known = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT",
                   "DOGE/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT"]
    current_active = get_active_assets()
    new_active = st.multiselect(
        t("cfg_watched_label"),
        options=all_known,
        default=current_active,
        help="Seuls les actifs ayant un fichier config/assets/*.yaml sont supportés.",
        key="marches_active_assets",
    )

    if st.button(t("cfg_save_assets"), key="btn_save_active_assets"):
        try:
            from utils.config import load_settings, save_settings
            from pathlib import Path
            cfg_path = Path("/app/data") / "settings.yaml" if Path("/app/data").is_dir() else Path(__file__).parent.parent / "config" / "settings.yaml"
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
        st.caption(t("cfg_risk_trend_caption"))
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
        st.caption(t("cfg_risk_range_caption"))
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

        if st.button(t("cfg_save_asset").format(asset=asset), key=f"save_{slug}"):
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
