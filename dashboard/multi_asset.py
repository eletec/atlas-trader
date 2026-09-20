"""
dashboard/multi_asset.py — Multi-asset UI components for Streamlit.

Exposed:
  - render_global_overview()    : consolidated table of all active assets
  - render_asset_tabs(main_fn)  : wrapper that injects the per-asset tabs
"""
from __future__ import annotations

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
    """Return the active carry assets from carry_assets.yaml (V7, no more DAGs)."""
    try:
        from v7.core.asset_config import get_active_assets as _cfg_active
        assets = _cfg_active()
        if assets:
            return assets
    except Exception:
        pass
    return ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT"]


def _asset_icon(asset: str) -> str:
    """Asset icon: local logo (upload) > git logo (images/assets/) > coloured circle fallback."""
    from pathlib import Path as _IPath
    import base64 as _b64

    ticker = asset.split("/")[0]

    # 1) Logo uploaded to /app/data/logos/ (icon_url in the config)
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

    # 2) Git-tracked logo in images/assets/{TICKER}.svg
    for ext in (".svg", ".png", ".webp", ".jpg"):
        git_path = _IPath("/app/src/images/assets") / f"{ticker}{ext}"
        if git_path.exists():
            return _img_b64(git_path)

    # 3) Coloured circle fallback
    return _fallback_icon_html(asset)


def _img_b64(path) -> str:
    """Encode an image as a base64 data URI."""
    import base64 as _b64
    ext = path.suffix.lower()
    mime = "image/svg+xml" if ext == ".svg" else ("image/webp" if ext == ".webp" else "image/png")
    data = _b64.b64encode(path.read_bytes()).decode()
    return (f'<img src="data:{mime};base64,{data}" width="16" height="16" '
            f'style="vertical-align:middle;border-radius:50%;">')


def _fallback_icon_html(asset: str) -> str:
    """Coloured circle with the token initials."""
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
    """Mini HTML progress bar for the score."""
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
# Component 1: global view (live data from the active DAGs)
# ---------------------------------------------------------------------------

_ACTION_TO_DIR = {"long": 75, "short": 25, "flat": 50, "hold": 50}


def render_global_overview() -> None:
    """
    Consolidated multi-asset table — V7 Funding Carry.
    Shows the state of each carry asset: position, funding, status.
    """
    import streamlit as st

    # V7: use carry_assets.yaml + paper_trader DB (no more DAGs)
    try:
        from v7.core.asset_config import get_active_assets
        assets = get_active_assets()
    except Exception:
        assets = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"]
    
    if not assets:
        return
    
    # Fetch open positions
    open_positions = {}
    try:
        from storage.paper_trader import get_open_positions
        all_open = get_open_positions()
        for pos in all_open:
            sym = pos.get("symbol", "")
            if sym:
                open_positions[sym] = pos
    except Exception:
        pass

    theme = st.query_params.get("theme", "dark")

    # Fetch latest carry status from dag_logs (V7 cycle writes there)
    asset_status = {}  # sym → {net_return, funding_rate, signal}
    try:
        import sqlite3, os, re
        db_path = os.environ.get("DATABASE_URL", "sqlite:////app/data/v4.db")
        if db_path.startswith("sqlite:///"):
            db_path = db_path[10:]
        conn = sqlite3.connect(db_path, timeout=10)
        # Get latest log per dag_id
        rows = conn.execute(
            "SELECT dag_id, message FROM dag_logs WHERE dag_id LIKE 'v7_%' "
            "ORDER BY id DESC LIMIT 200"
        ).fetchall()
        seen = set()
        for dag_id, msg in rows:
            sym = dag_id[3:].upper()  # v7_btc → BTC
            if sym in seen:
                continue
            seen.add(sym)
            # Parse net return
            m = re.search(r'net=([\d.]+)%/an', msg)
            net_ret = float(m.group(1)) if m else None
            m = re.search(r'funding=(-?[\d.]+)%', msg)
            funding = float(m.group(1)) if m else None
            m = re.search(r'retour net ([\d.]+)%/an', msg)
            ret_net = float(m.group(1)) if m else None
            asset_status[sym] = {
                "net_return": net_ret or ret_net,
                "funding_rate": funding,
                "signal": "open_carry" if "open_carry" in msg else "flat",
            }
        conn.close()
    except Exception:
        pass

    html_rows = ""
    for asset in assets:
        base = asset.split("/")[0].upper()
        pos = open_positions.get(asset, {})
        has_position = bool(pos)
        size_usd = float(pos.get("size_usd", 0) or 0)
        entry_price = float(pos.get("entry_price", 0) or 0)
        
        icon = _asset_icon(asset) if asset else "◈"
        ts_str = pos.get("timestamp", "—")[:19] if pos.get("timestamp") else "—"
        
        # Get latest cycle status
        st_info = asset_status.get(base, {})
        net_ret = st_info.get("net_return")
        funding = st_info.get("funding_rate")
        cycle_signal = st_info.get("signal", "flat")
        
        # Score: the real strategy score (risk budget, stored in context_json)
        # for open positions; the net_return/funding heuristic otherwise.
        if has_position:
            score = None
            _ctx_raw = pos.get("context_json")
            if _ctx_raw:
                try:
                    import json as _jsc
                    _ctx = _jsc.loads(_ctx_raw) if isinstance(_ctx_raw, str) else _ctx_raw
                    if isinstance(_ctx, dict) and _ctx.get("score") is not None:
                        score = int(_ctx.get("score", 0))
                except Exception:
                    pass
            if score is None:
                score = 75  # fallback when context is absent
            signal_display = "💸 carry"
            trade_str = f"🟢 CARRY ${size_usd:,.0f}"
            trend = f"entry @ ${entry_price:,.2f}"
        elif net_ret is not None and net_ret > 5:
            score = min(95, int(50 + net_ret * 3))
            signal_display = "⏳ viable"
            trade_str = f"net {net_ret:.1f}%/yr"
            trend = f"funding {funding:.4f}%" if funding else "—"
        elif net_ret is not None:
            score = max(5, int(30 + net_ret * 4))
            signal_display = "flat"
            trade_str = f"net {net_ret:.1f}%/yr < 5%"
            trend = f"funding {funding:.4f}%" if funding else "—"
        elif funding is not None:
            score = max(5, min(50, int(20 + funding * 200)))
            signal_display = "flat"
            trade_str = f"funding {funding:.4f}%"
            trend = f"outside [min=0.0050%]" if funding < 0.005 else "—"
        else:
            score = 50
            signal_display = "flat"
            trade_str = "—"
            trend = "—"

        status_icon = "🟢" if has_position else "⚫"
        status_text = "CARRY" if has_position else "idle"

        html_rows += (
            f"<tr>"
            f"<td style='padding:6px 10px;'>{icon} {asset}</td>"
            f"<td style='padding:6px 10px;'>{_action_badge(signal_display)}</td>"
            f"<td style='padding:6px 10px;'>{_score_bar(score, theme)}</td>"
            f"<td style='padding:6px 10px;font-size:12px;opacity:.7;'>{ts_str}</td>"
            f"<td style='padding:6px 10px;font-size:12px;'>{trade_str}</td>"
            f"<td style='padding:6px 10px;font-size:12px;'>{trend}</td>"
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
# Component 1b: multi-asset live prices (cards) — V4 API
# ---------------------------------------------------------------------------

@st.cache_data(ttl=15)
def _fetch_v4_prices() -> dict[str, dict]:
    """Fetch the live prices from the V4 API (Binance WebSocket)."""
    try:
        import urllib.request, json
        req = urllib.request.Request(f"{_API_BASE}/prices/snapshot")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read())
    except Exception:
        return {}


def render_global_live_prices() -> None:
    """Live price grid - AJAX polling every 3s, no page refresh."""
    import streamlit as st
    import json as _json
    import traceback as _tb

    # V7 (DeepSeek/GPT audit, 25/07/2026): use carry_assets.yaml, no more DAGs
    dag_assets = []
    _load_error = ""
    try:
        from v7.core.asset_config import get_active_assets
        dag_assets = get_active_assets()
    except Exception as e:
        _load_error = f"get_active_assets() failed: {e}"
        dag_assets = []
    
    if not dag_assets:
        dag_assets = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"]
    
    prices = {}
    try:
        prices = _fetch_v4_prices()
    except Exception:
        pass

    st.markdown(f"### 📡 {t('live_price_title')}")

    # Fetch open carry positions from paper_trader DB (V7: no DAGs)
    open_positions = {}
    try:
        from storage.paper_trader import get_open_positions
        all_open = get_open_positions()
        for pos in all_open:
            sym = pos.get("symbol", "")
            if sym and pos.get("action") in ("carry", "short"):
                open_positions[sym] = pos
    except Exception:
        pass

    # Build the HTML cards with data attributes for the JS
    cards = ""
    pos_data = {}  # sym → {action, entry, size}
    for asset in dag_assets:
        icon = _asset_icon(asset)
        pdata = prices.get(asset, {})
        price = pdata.get("price")
        price_str = _fmt_price(price)
        init_price = price or 0

        # V7: position info from paper_trader DB (no DAGs)
        pos = open_positions.get(asset)
        if pos:
            size_usd = float(pos.get("size_usd", 0) or 0)
            entry_price = float(pos.get("entry_price", 0) or 0)
            if size_usd > 0:
                pos_data[asset] = {"action": "carry", "entry": entry_price or (price or 0), "size": size_usd}
                pos_html = f'<span style="color:#f39c12">CARRY ${size_usd:,.0f}</span>'
            else:
                pos_html = "—"
            # Get funding from price data if available
            funding_rate = pdata.get("funding_rate", 0)
            trend_label = f"funding {funding_rate*100:.4f}%" if funding_rate else "—"
            sig_label = "CARRY ACTIVE"
        else:
            pos_html = "—"
            funding_rate = pdata.get("funding_rate", 0)
            trend_label = f"funding {funding_rate*100:.4f}%" if funding_rate else "—"
            sig_label = "flat"

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
    
    # Dynamic height: ~4.5 cards per row, ~90px per row, minimum 200px
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

      // Change %
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

      // Position unrealized PnL
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
    """Format a price for display."""
    if price is None:
        return "—"
    if price >= 1000:
        return f"${price:,.0f}"
    if price >= 1:
        return f"${price:,.2f}"
    return f"${price:.4f}"


# ---------------------------------------------------------------------------
# Component 2: per-asset tabs
# ---------------------------------------------------------------------------

def _inject_custom_sidenav(items: list, active_key: str, qparam: str = "_asset", theme: str = "dark") -> None:
    """Inject a fixed sidebar into the parent document (independent of st.sidebar).
    items  : list of dicts {key, icon, text}
    active_key : key of the active item
    qparam : name of the query parameter used for navigation
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

  /* Streamlit header height (measured dynamically) */
  function hdrH() {{
    var h = d.querySelector('[data-testid="stHeader"]');
    return (h && h.getBoundingClientRect().height > 10)
           ? h.getBoundingClientRect().height : 60;
  }}

  var collapsed = p.localStorage.getItem('atlas_nav_c') === '1';

  /* ── Dropdown CSS injected into the parent HEAD (popovers are portaled into the parent) ── */
  if (!d.getElementById('atlas-dropdown-css')) {{
    var dropS = d.createElement('style');
    dropS.id = 'atlas-dropdown-css';
    dropS.textContent = [
      '[data-baseweb="popover"] {{ min-width: max-content !important; }}',
      'ul[data-baseweb="menu"] li, [data-baseweb="option"] {{ white-space: nowrap !important; }}'
    ].join(' ');
    d.head.appendChild(dropS);
  }}

  /* Navigation link: reuses the current URL (lang/theme/admin/_sid) and only
     changes the section key. We force menu=0, otherwise the hamburger stayed
     open indefinitely: each navigation copied menu=1 over to the next one. */
  function navUrl(key) {{
    var u = new URL(p.location.href);
    u.searchParams.set(QPARAM, key);
    u.searchParams.set('menu', '0');
    return u.toString();
  }}

  function setPad(c) {{
    var w = (c ? MINI : W) + 'px';
    /* Persistent style tag in <head> — immune to Streamlit React rerenders,
       unlike inline styles which are reset on every widget interaction. */
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

  /* CSS — updated on every render to reflect the current theme */
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

  /* Build the nav */
  var existing = d.getElementById('atlas-sidenav');
  var wasC = existing ? existing.classList.contains('c') : collapsed;
  var nav = d.createElement('div');
  nav.id = 'atlas-sidenav';
  if (wasC) nav.classList.add('c');

  nav.innerHTML =
    '<div id="ant" title="Collapse / Expand">&#9776;</div>' +
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

  /* Re-position when the header changes size */
  var ro = new p.ResizeObserver(function() {{ positionNav(d.getElementById('atlas-sidenav')); }});
  var hdrEl = d.querySelector('[data-testid="stHeader"]');
  if (hdrEl) ro.observe(hdrEl);

  d.getElementById('ant').addEventListener('click', function() {{
    var n = d.getElementById('atlas-sidenav');
    var c = n.classList.toggle('c');
    p.localStorage.setItem('atlas_nav_c', c ? '1' : '0');
    setPad(c);
  }});

  /* ── BaseWeb dropdown width fix — removes the inline width injected by useEffect ── */
  if (!p._atlasDropMo) {{
    /* Fix a popover: remove width + observe later rewrites */
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
          /* Case 1: the popover itself is added */
          if (node.getAttribute && node.getAttribute('data-baseweb') === 'popover') {{
            _atlasFixPop(node);
          }}
          /* Case 1b: popover as a descendant */
          Array.prototype.slice.call(
            node.querySelectorAll('[data-baseweb="popover"]')
          ).forEach(_atlasFixPop);
          /* Case 2: the menu is added into an already existing popover (deferred render) */
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
    Fixed side menu (position:fixed in the parent DOM) — sticky, collapsible/expandable.
    Navigation through the _asset query param, with no dependency on st.sidebar.
    When only one asset is active, goes straight to render_fn without navigation.
    """
    import streamlit as st

    assets = _active_assets()

    if len(assets) <= 1:
        render_fn(assets[0] if assets else "BTC/USDT")
        return

    # Double space between icon and text for the split
    labels = ["🌐  Global"] + [f"{_asset_icon(a)}  {a}" for a in assets]
    # URL-safe keys (e.g. 'BTC_USDT')
    keys   = ["Global"] + [a.replace("/", "_") for a in assets]

    # Selection read from the URL (persisted, no Streamlit localStorage)
    selected_key = st.query_params.get("_asset", "Global")
    if selected_key not in keys:
        selected_key = "Global"

    # Items for the JS [{key, icon, text}, ...]
    items = []
    for k, lbl in zip(keys, labels):
        parts = lbl.split("  ", 1)
        items.append({"key": k, "icon": parts[0], "text": parts[1] if len(parts) > 1 else parts[0]})

    _inject_custom_sidenav(items, selected_key, theme=st.query_params.get("theme", "dark"))

    # Render the selected view
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
