"""
dashboard/streamlit_app.py — Dashboard principal Atlas Trader
Interface User (lecture seule) + Interface Admin (protégée par mot de passe).
"""
from __future__ import annotations

import html
import os
import shlex
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from queue import Queue, Empty


# ── Background backtest run ─────────────────────────────────────────────
# A multi-asset sweep takes minutes, so it runs detached and we follow a log
# file. The marker files live on the shared v4_storage volume.
_BT_LOG = "/app/data/backtest_run.log"
_BT_RC = "/app/data/backtest_run.rc"


def _backtest_run_state() -> str:
    """'idle' when nothing was started, 'running' or 'done'."""
    if not os.path.exists(_BT_LOG):
        return "idle"
    return "done" if os.path.exists(_BT_RC) else "running"


def _backtest_exit_code() -> int:
    try:
        with open(_BT_RC, encoding="utf-8", errors="replace") as fh:
            return int((fh.read().strip() or "0"))
    except (OSError, ValueError):
        return 0


def _fmt_utc_local(dt_utc: datetime) -> str:
    """Format 'DD/MM/YYYY HH:MM UTC (HH:MM local)' where local = Europe/Paris."""
    try:
        from zoneinfo import ZoneInfo
        local_tz = ZoneInfo("Europe/Paris")
    except Exception:
        local_tz = timezone(timedelta(hours=1))  # fallback UTC+1
    local_dt = dt_utc.replace(tzinfo=timezone.utc).astimezone(local_tz)
    return f"{dt_utc.strftime('%d/%m/%Y %H:%M')} UTC ({local_dt.strftime('%H:%M')} local)"

# Make sure /app (or the parent of the current folder) is first on sys.path
# to avoid clashes with third-party 'utils' packages
_APP_ROOT = str(Path(__file__).resolve().parent.parent)
if _APP_ROOT not in sys.path:
    sys.path.insert(0, _APP_ROOT)


# 34x34 logo extracted from atlas.ico (base64 PNG ~3KB - no file dependency)
_LOGO_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAACIAAAAiCAYAAAA6RwvCAAAJfklEQVR4nH2YC5DVVR3HP+f//9/3"
    "vfuQpzxCxFxEFAQRxZyaUsSYfKSOoYVZOk2TiTWNFRDOmKbYNGONUxPqMBNiNYqhOY1KoC4KDpKA"
    "iJiLFqQGCyzL7n3+X6c5j//du6Cdu3fu+Z//Ob/zPd/f86wYNWGuBAFCEKOaUE/mVzhI84DjOPpZ"
    "jUfCzBESpBBIIc2zHhcI6Wp5IM1iMSTVNDVunu0MvGbXvhPJSiRSRggUGIGUaoLU8h0NwM6XLYDs"
    "UinUOitJOM3+0PYWnwWrZHtxrAYMKaCEmc2a+GRsxxUbpq8ZUgCNmKZA/acQWllKkFqvXlsO0efR"
    "ICC2h1Mn8YwIsyhp5vRDTeFUIAyYZI7aQODozdQkC1KfycrS4wqq+ijVKhmGpSF6LCPqAPoQSppo"
    "Ja65pd1ADgOjpioBZpmD0EKUvagVcZMBYjWm7M1saDhUH9U1dqjmeUPUKzDCgmkai4ViGNK2ISMz"
    "xwpI2DE8KENN1io4lguNzrAgnMTeEgKNi3jqSMN4kNIYYouuDVHC6rTF3h0DSHtXFDXVRWxYVJ6m"
    "rEnDERG4LnEQGO9yXMuysS1vmE0Is4E6VROMpiLxALM2CkNoxEadYYiIYkRbESeVNkIUAMWSMq44"
    "1nYUxxI5OEh2RBuhcAhrdQtGqTU2qjF6MshQalL7xjHCcZCOIKpWDe1RhJvPkx3VSefU05GuR5DL"
    "kj5vOn2PP43/Ya9mRdZ9RC6H9AOcQk7jSaVTdCxZRPa6hfTefCfBQBknowBHn8AI1o2VuhS4KIJq"
    "leyZZ9B+4WyK07sId++hFgTExSLOjOmkbrqS4LUdiD+sI67XaZs1nczkCdS37SI9eRLlHXvwqzWc"
    "fJZwahe9a58hOD6Io9iIkv1AdIydKVXQGu6vwmjEdSnd/j28a67EaSsSrV6N8+5eUjPPpX/NkzBz"
    "OsEH+8kc7cPt7CBKeXQsuY26myY9ZQrRmDF4z29gcMUD5O9bTv+f/kL0/CYYO1qrNXECw4iMbZgy"
    "3iKU/bku0aGDtN+1FLFoMf7H/0VUYtyzz0POmkOtXsadOI7BtetwOtuppVO0zz6X0qXzieM0UedY"
    "yjJD/FYP3s63Kd13N33PPEe48SWccaORQWhcuhm/YjwViJSxKN8ROpynkJUKhSu+QmrBVfj/OawU"
    "jAwFjdAleOZpgqeeRBaLiLGjjHFGEY1TTyOu1Anf3Ik7aw5y6+t4L75AdvEt9L35NrliG7KznbDR"
    "0C6sDNEGBW0K2kZMzkiiYaitPX39zQTpEvLjDxGeQ7h9C9WHHjCslUo4CryS5DfwCllyU2cSS0Hm"
    "lPGEv3uYVKkDb8lSjv9tPU7nKLhzOZneXvzNm3GKJe0MNidoXRiv0V0TflCG40oqj68i/51l+GtW"
    "EW7vJg4DEzHzRRNTYokoH4F8iezSh6iP/yxhNg9HjtE2+xKiSxZw/PcP482+GNE1ndoD95JSe3uu"
    "CYo6JCeRW9lIHCO1+5oIJ20c8N94BemHpKfPJVso0djxKukzRhMeOUjw8Ydk2jrovP3nhAf3U397"
    "J7I4BmfTanI4NM6ZS+2J1WS+cC1eUCbcfwC/+0UalUFkNqeDnw58OsTbJNI+ssuk21b1qOZ6yGoZ"
    "cnkyk6aSu/5HMPVCwhcfRWzbQO6rdzCwbyfp0Z8hpzT01kt453yeerGTcMtzpBcsJh4xFtGoEqy+"
    "B3/361BsMyHBphCTTG0M1B2diU8oXKIAUShBUCeuNZDZMfjrHiY1WMe79FtUdnTj7f0HlVXLGPig"
    "B+/y71M+1Iv/2M/IX/5tSHXgVCOCDU8R7NmKKHVoe1KOob9xBHGEUIFTqVkzMqwJozvtWS4yDrU+"
    "SxdcTWr8WQTVfkSjRuaiGwmOHuD4o7ci/Qh31GTi3v2kT51M8dbfEImMDvPBq4/jZnJUuv+cHHF4"
    "brPVnpdEVVPcMCzUx34FN1eiOGMhMn8KlV2bKM65AWfKPMK+A9T+vgqp8kyhRNT/ESKbJ6weQw7U"
    "cEeOo7L+buKD7xN4aQgbiHTOekuzCLRJViDaRpw5jBGRAJIR6ZGnk544i+DYAWrvdeMWRzDqtvXa"
    "fgb+upT6extxiqNVFtTCdJ4KamSnLdAi/Hc2gpMCIkQqa7Pt0D6KBP2rnk8EoprKM+lTJoCXw+/t"
    "IW6UcfPtxPUB8mctpHD21Rx59gdWfQmT9ld5YFAxm2TahwqkZok4VP8atdga8WQgEoSHo7KuX8Hx"
    "MgjHIwpVHeFAWCU9fq5mLDi8xxZIVveqdHQcXZ+5rkMchvpZvYsipRJXvbF1ylDTNjIchGoKY4Tf"
    "CNGB11cAQgqFAnEc45PH6dtNhEsYxnjuUDWnwFfKFXK5LIOVBsVigXKliue5dHS0a7i+HxIEvk4n"
    "hgwFVJwMRAhBFEZ0tJdYef9yXNflp8t+wQ3XLeS00yfzmYnjeGfvPrZseYOL553PmrXreP9fByjk"
    "chw92sdVV17OLd9cxObNW3lw5a+57Ir53LToanp63ieVzrDp5dfYtn2XBqtVlGT6VhBSUeu5lPuP"
    "8uO77tQLXn5lK3ev+AkPrlzJE39cj5Qey1fcz4aN3cyadR6D5SqVY30cPnKUkaNGsuSO77J02T3M"
    "n38psy+4QBtyJpPn0KEjDAzWqNWCZuVvvqaoHgbEFYLy8QG+eNmXOHtaF6seWcMjj61l4oRTmf/l"
    "a+jvP24yJw5+ELL/wEcs/vp1fO2m65l7/gxWLP8hzz73Art3vs4vf/Vb7rt3Ke/+s4fuV7dSKhb4"
    "3Lw5fOPGa6kOlm391eJF2liTIhkV/BpMm9al9diz7996dNJp4ykVS+z7YD9ndU1h1+692jqLxRzz"
    "LppDJp2m9/ARZCzZ9dYe/DAiDALOnz2Daq3GlMmTCMOQRsNn2/adNFQpaetgk14+JY7U63UNLJvN"
    "6DElQBlqOpuhUauTz+f04jCMqJTLmmPXM+am3inq1ftKpaptrNFo2KpeUCjk9dhJl7gmIy3jQl8R"
    "VBC013LrblqX6l6iKnLrdvpk6jqh6wppqvUWVSdrzPrWS5m+rDbDvWdqkKGrt2q6Em/JjDIJy6pY"
    "0AWvmalH9R0mGnaWRFpkhejaxQhuyjFdeyDlJFqcuoPYSbI5NVlx4kDzaPy/llzbT7rEnnStNazp"
    "S7j5H4Ctzkhu8a3h+1M2S8C3XuA/EZT5xjbTJhnXBnpdl3jJUOLHWnNKNbaC0qBaz5Vc91oSaOsF"
    "3qawIeZaEukJptjsq73+B/YmhGGSDxKwAAAAAElFTkSuQmCC"
)

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils.i18n import t, set_lang

# ── API URL (Docker = atlas-v4-api, local = host.docker.internal) ──────────
import os as _os
_API_BASE = _os.environ.get("V4_API_URL", "http://host.docker.internal:8000")

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
    """Read the theme from the query params (dark by default)."""
    return st.query_params.get("theme", "dark")


def _inject_theme_css():
    """Inject the CSS overrides for the selected theme."""
    theme = _get_theme()

    # Font Awesome 6 (modern monochrome icons)
    st.markdown(
        '<link rel="stylesheet" '
        'href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css" '
        'integrity="sha512-Avb2QiuDEEvB4bZJYdft2mNjVShBftLdPG8FJ0V7irTLQ8Uo0qcPxh4Plq7G5tGm0rU+1SPhVotteLpBERwTkw==" '
        'crossorigin="anonymous">',
        # S6: the SRI hash protects against CDN substitution
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
        /* Selectbox / dropdowns BaseWeb */
        [data-baseweb="select"] > div:first-child {
            background-color: #ffffff !important;
            border-color: #ced4da !important;
        }
        [data-baseweb="select"] span,
        [data-baseweb="select"] div { color: #31333F !important; }
        /* Input text/number */
        [data-baseweb="input"],
        [data-testid="stTextInput"] input,
        [data-testid="stNumberInput"] input {
            background-color: #ffffff !important;
            color: #31333F !important;
            border-color: #ced4da !important;
        }
        /* Textarea */
        textarea, [data-baseweb="textarea"] textarea {
            background-color: #ffffff !important;
            color: #31333F !important;
            border-color: #ced4da !important;
        }
        /* Number input arrows */
        [data-testid="stNumberInput"] button {
            background-color: #ffffff !important;
            color: #31333F !important;
            border-color: #ced4da !important;
        }
        /* Selectbox dropdown menu */
        ul[data-baseweb="menu"] {
            background-color: #ffffff !important;
            border-color: #dee2e6 !important;
        }
        ul[data-baseweb="menu"] li,
        [data-baseweb="option"] {
            background-color: #ffffff !important;
            color: #31333F !important;
            white-space: nowrap !important;
        }
        ul[data-baseweb="menu"] li:hover,
        [data-baseweb="option"]:hover {
            background-color: #f0f2f6 !important;
        }
        /* Form container */
        [data-testid="stForm"] {
            background-color: #ffffff !important;
            border: 1px solid #dee2e6 !important;
            border-radius: 10px !important;
        }
        input, input[type="text"], input[type="password"] {
            background-color: #ffffff !important;
            color: #31333F !important;
            border-color: #ced4da !important;
        }
        /* Slider labels */
        [data-testid="stSlider"] span { color: #31333F !important; }
        /* ── Tous les boutons (stBaseButton couvre télécharger, upload, etc.) ── */
        .stButton > button,
        .stButton button,
        button[data-testid^="stBaseButton"],
        [data-testid="stFormSubmitButton"] button,
        [data-testid="stDownloadButton"] button,
        [data-testid="stFileUploaderDeleteBtn"] button {
            background-color: #ffffff !important;
            color: #31333F !important;
            border: 1px solid #ced4da !important;
        }
        button[data-testid="stBaseButton-primary"],
        [data-testid="stFormSubmitButton"] button[kind="primary"] {
            background-color: #ff4b4b !important;
            color: #ffffff !important;
            border: none !important;
        }
        /* Boutons internes inputs (œil password, etc.) */
        [data-testid="stTextInput"] button,
        [data-testid="stPasswordInput"] button,
        [data-baseweb="input"] button {
            background-color: transparent !important;
            color: #31333F !important;
            border: none !important;
            box-shadow: none !important;
        }
        [data-testid="stTextInput"] button svg,
        [data-testid="stPasswordInput"] button svg,
        [data-baseweb="input"] button svg {
            fill: #31333F !important;
        }
        /* ── Radio buttons — texte sombre, cercle gris (pas noir) ── */
        [data-testid="stRadio"] label,
        [data-testid="stRadio"] p { color: #31333F !important; }
        /* Le cercle utilise currentColor comme border/fill → on le met gris pour éviter noir plein */
        [data-baseweb="radio"] { color: rgba(49,51,63,0.45) !important; }
        [data-baseweb="radio"][aria-checked="true"],
        [data-baseweb="radio"][data-checked="true"] { color: #ff4b4b !important; }
        /* ── Toggle — piste OFF visible + piste ON rouge ── */
        [data-testid="stToggle"] label,
        [data-testid="stToggle"] p { color: #31333F !important; }
        /* Piste du toggle : plusieurs sélecteurs pour couvrir les versions Streamlit */
        [data-testid="stToggle"] [role="checkbox"],
        [data-testid="stToggle"] label > div:first-child,
        [data-baseweb="toggle"] {
            background-color: #ced4da !important;
            border-color: #adb5bd !important;
        }
        [data-testid="stToggle"] [role="checkbox"][aria-checked="true"],
        [data-baseweb="toggle"][aria-checked="true"] {
            background-color: #ff4b4b !important;
            border-color: #ff4b4b !important;
        }
        /* ── Tabs ── */
        [data-testid="stTabs"] [data-baseweb="tab-list"] {
            background-color: #f8f9fa !important;
            border-bottom: 1px solid #dee2e6 !important;
            box-shadow: none !important;
        }
        [data-testid="stTabs"] button[role="tab"] {
            color: rgba(49,51,63,0.6) !important;
            background-color: transparent !important;
        }
        [data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
            color: #31333F !important;
            border-bottom-color: #ff4b4b !important;
        }
        [data-testid="stTabs"] [data-baseweb="tab-panel"] {
            background-color: transparent !important;
        }
        /* ── Expanders ── */
        [data-testid="stExpander"] {
            background-color: #ffffff !important;
            border: 1px solid #dee2e6 !important;
        }
        [data-testid="stExpanderHeader"],
        [data-testid="stExpander"] summary {
            background-color: #f0f2f6 !important;
            color: #31333F !important;
        }
        [data-testid="stExpanderDetails"] {
            background-color: #ffffff !important;
        }
        /* ── File uploader ── */
        [data-testid="stFileUploader"],
        [data-testid="stFileUploadDropzone"],
        [data-baseweb="file-uploader"] {
            background-color: #ffffff !important;
            border: 1px dashed #ced4da !important;
            color: #31333F !important;
        }
        [data-testid="stFileUploadDropzone"] button,
        [data-testid="stFileUploadDropzone"] span,
        [data-testid="stFileUploadDropzone"] p,
        [data-testid="stFileUploader"] label,
        [data-testid="stFileUploader"] span,
        [data-testid="stFileUploader"] small { color: #31333F !important; }
        /* ── Table st.table ── */
        [data-testid="stTable"] table {
            background-color: #ffffff !important;
            border-collapse: collapse !important;
            width: 100% !important;
        }
        [data-testid="stTable"] thead th {
            background-color: #f0f2f6 !important;
            color: #31333F !important;
            border-bottom: 1px solid #dee2e6 !important;
            padding: 8px 12px !important;
        }
        [data-testid="stTable"] tbody td {
            background-color: #ffffff !important;
            color: #31333F !important;
            border-bottom: 1px solid #f0f2f6 !important;
            padding: 6px 12px !important;
        }
        [data-testid="stTable"] tbody tr:hover td {
            background-color: #f8f9fa !important;
        }
        /* ── Dialog modal ── */
        div[role="dialog"],
        [data-baseweb="dialog"] {
            background-color: #ffffff !important;
            border: 1px solid #dee2e6 !important;
            max-width: 560px !important;
        }
        div[role="dialog"] p,
        div[role="dialog"] label { color: #31333F !important; }
        div[role="dialog"] button[aria-label="Close"],
        div[role="dialog"] button[data-testid="stBaseButton-headerNoPadding"] {
            background-color: transparent !important;
            border: none !important;
            box-shadow: none !important;
        }
        div[role="dialog"] button[aria-label="Close"] svg,
        div[role="dialog"] button[data-testid="stBaseButton-headerNoPadding"] svg {
            fill: rgba(49,51,63,0.7) !important;
        }
        /* ── DataFrames ── */
        [data-testid="stDataFrame"], .stDataFrame { background-color: #ffffff !important; }
        [data-testid="stDataFrame"] * { color: #31333F !important; }
        [data-testid="stDataFrameResizable"] { background-color: #ffffff !important; }
        [data-testid="stAlert"] { background-color: #e8f4fd !important; }
        hr { border-color: #dee2e6 !important; }
        code, pre { background-color: #f1f3f5 !important; color: #31333F !important; }
        /* Selectbox dropdown — min-width + fond blanc sur popover ET liste */
        [data-baseweb="popover"] { min-width: max-content !important; }
        [data-baseweb="popover"],
        [data-baseweb="popover"] > div,
        [data-baseweb="popover"] [data-baseweb="block"],
        [data-baseweb="list"],
        [role="listbox"] {
            background-color: #ffffff !important;
            color: #31333F !important;
        }
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
        /* Selectbox dropdown — min-width !important bat le style inline injecte par BaseWeb */
        [data-baseweb="popover"] { min-width: max-content !important; }
        ul[data-baseweb="menu"] {
            background-color: #21262d !important;
            border-color: rgba(255,255,255,0.15) !important;
        }
        ul[data-baseweb="menu"] li,
        [data-baseweb="option"] {
            background-color: #21262d !important;
            color: #FAFAFA !important;
            white-space: nowrap !important;
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
        /* Agrandir bouton tooltip pour loger SVG 16px — déplacé dans atlas-tooltip-global */
        /* Table (st.table) fond sombre */
        [data-testid="stTable"] table {
            background-color: #161b22 !important;
            border-collapse: collapse !important;
            width: 100% !important;
        }
        [data-testid="stTable"] thead th {
            background-color: #21262d !important;
            color: #FAFAFA !important;
            border-bottom: 1px solid rgba(255,255,255,0.15) !important;
            padding: 8px 12px !important;
        }
        [data-testid="stTable"] tbody td {
            background-color: #161b22 !important;
            color: #FAFAFA !important;
            border-bottom: 1px solid rgba(255,255,255,0.07) !important;
            padding: 6px 12px !important;
        }
        [data-testid="stTable"] tbody tr:hover td {
            background-color: #21262d !important;
        }
        /* ── Expanders — fond sombre, header focus sans blanc ── */
        [data-testid="stExpander"] {
            background-color: #161b22 !important;
            border: 1px solid rgba(255,255,255,0.1) !important;
        }
        [data-testid="stExpanderHeader"],
        [data-testid="stExpander"] summary {
            background-color: #161b22 !important;
            color: #FAFAFA !important;
        }
        /* Supprimer le fond blanc au focus/actif */
        [data-testid="stExpanderHeader"]:focus,
        [data-testid="stExpanderHeader"]:active,
        [data-testid="stExpander"] summary:focus,
        [data-testid="stExpander"] summary:active {
            background-color: #21262d !important;
            color: #FAFAFA !important;
            outline: none !important;
        }
        [data-testid="stExpanderHeader"]:hover,
        [data-testid="stExpander"] summary:hover {
            background-color: #21262d !important;
        }
        [data-testid="stExpanderDetails"] {
            background-color: #0d1117 !important;
        }
        /* Tabs navigation — sticky sous la navbar */
        [data-testid="stTabs"] [data-baseweb="tab-list"] {
            background-color: #0e1117 !important;
            box-shadow: 0 2px 8px rgba(0,0,0,0.45) !important;
        }
        [data-testid="stTabs"] button[role="tab"] {
            color: rgba(255,255,255,0.6) !important;
            background-color: transparent !important;
        }
        [data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
            color: #FAFAFA !important;
            border-bottom-color: #ff4b4b !important;
        }
        /* Dialog modal — fond sombre + taille compacte */
        div[role="dialog"],
        [data-baseweb="dialog"] {
            background-color: #1c2128 !important;
            border: 1px solid rgba(255,255,255,0.15) !important;
            max-width: 560px !important;
        }
        /* Texte dans le dialog — SAUF bouton X et ses enfants */
        div[role="dialog"] p,
        div[role="dialog"] label {
            color: #FAFAFA !important;
        }
        /* Bouton X (fermeture) : fond transparent + icône visible */
        div[role="dialog"] button[aria-label="Close"],
        div[role="dialog"] button[data-testid="stBaseButton-headerNoPadding"] {
            background-color: transparent !important;
            border: none !important;
            box-shadow: none !important;
        }
        div[role="dialog"] button[aria-label="Close"] svg,
        div[role="dialog"] button[data-testid="stBaseButton-headerNoPadding"] svg {
            fill: rgba(255,255,255,0.8) !important;
            stroke: rgba(255,255,255,0.8) !important;
        }
        div[role="dialog"] button[aria-label="Close"]:hover svg,
        div[role="dialog"] button[data-testid="stBaseButton-headerNoPadding"]:hover svg {
            fill: #ffffff !important;
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

    # CSS global : onglets scrollables horizontalement + restauration espacement vertical
    st.markdown("""
    <style>
    div[data-baseweb="tab-list"] {
        overflow-x: auto !important;
        overflow-y: hidden !important;
        flex-wrap: nowrap !important;
        scrollbar-width: thin;
    }
    div[data-baseweb="tab-list"]::-webkit-scrollbar { height: 3px; }
    div[data-baseweb="tab"] {
        white-space: nowrap !important;
        flex-shrink: 0 !important;
    }

    /* ── Restauration espacement vertical global ──────────────────────────────
       Le menu custom (atlas-pad-css dans <head> parent) peut interférer avec
       les gaps Streamlit. On restaure explicitement l'espacement attendu.     */

    /* Gap entre blocs verticaux Streamlit */
    [data-testid="stVerticalBlock"] { gap: 1rem !important; }

    /* Marge basse sur chaque enfant direct (double protection si gap ne s'applique pas) */
    [data-testid="stVerticalBlock"] > div { margin-bottom: 0.5rem; }
    [data-testid="stVerticalBlock"] > div:last-child { margin-bottom: 0; }

    /* Padding haut du conteneur de contenu principal */
    [data-testid="stMainBlockContainer"] {
        padding-top: 2rem !important;
        padding-bottom: 3rem !important;
    }

    /* Titres Markdown h3/h4/h5 — marges explicites */
    [data-testid="stMarkdownContainer"] h3 {
        margin-top: 1.5rem !important;
        margin-bottom: 0.6rem !important;
    }
    [data-testid="stMarkdownContainer"] h4 {
        margin-top: 1.25rem !important;
        margin-bottom: 0.5rem !important;
    }
    [data-testid="stMarkdownContainer"] h5 {
        margin-top: 2rem !important;
        margin-bottom: 0.5rem !important;
    }

    /* Blocs info / warning / error */
    [data-testid="stAlertContainer"] {
        margin-top: 0.25rem !important;
        margin-bottom: 0.75rem !important;
    }

    /* Espace avant les onglets st.tabs */
    [data-testid="stTabs"] {
        margin-top: 0.5rem !important;
    }

    /* Séparateur st.divider */
    [data-testid="stMarkdownContainer"] hr {
        margin-top: 1.25rem !important;
        margin-bottom: 1.25rem !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # Global CSS for Streamlit tooltips (rendered into body via a React portal)
    # Always injected - colours adapted to the current theme
    if theme == "light":
        _t_bg, _t_fg, _t_bdr, _t_sh = "#ffffff", "#31333F", "#dee2e6", "rgba(0,0,0,0.14)"
        _t_icon_fg   = "#6c757d"   # couleur du ? au repos
        _t_icon_fg_h = "#31333F"   # couleur au survol
        _t_icon_bg   = "rgba(0,0,0,0.05)"
        _t_icon_bg_h = "rgba(0,0,0,0.10)"
        _t_icon_bdr  = "rgba(0,0,0,0.18)"
    else:  # dark ou system
        _t_bg, _t_fg, _t_bdr, _t_sh = "#21262d", "#e6edf3", "rgba(255,255,255,0.18)", "rgba(0,0,0,0.55)"
        _t_icon_fg   = "rgba(255,255,255,0.70)"
        _t_icon_fg_h = "#ffffff"
        _t_icon_bg   = "rgba(255,255,255,0.08)"
        _t_icon_bg_h = "rgba(255,255,255,0.18)"
        _t_icon_bdr  = "rgba(255,255,255,0.22)"
    st.markdown(f"""
<style id="atlas-tooltip-global">
/* ── Bulle tooltip (portal Radix — hors DOM principal) ── */
div[data-radix-popper-content-wrapper] {{
    background-color: {_t_bg} !important;
    color: {_t_fg} !important;
    border: 1px solid {_t_bdr} !important;
    border-radius: 6px !important;
    box-shadow: 0 4px 16px {_t_sh} !important;
    padding: 7px 11px !important;
    font-size: 12px !important;
    line-height: 1.5 !important;
    max-width: 340px !important;
}}
div[data-radix-popper-content-wrapper] *,
[role="tooltip"],
[role="tooltip"] * {{
    border: none !important;
    background: transparent !important;
    box-shadow: none !important;
    color: {_t_fg} !important;
    padding: 0 !important;
    margin: 0 !important;
}}

/* ── Bouton icône ? — sélecteurs Streamlit connus ── */
button[data-testid="stTooltipHoverTarget"],
button[data-testid="stTooltipIcon"] {{
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    width: 20px !important;
    height: 20px !important;
    min-width: 20px !important;
    border-radius: 50% !important;
    border: 1px solid {_t_icon_bdr} !important;
    background: {_t_icon_bg} !important;
    padding: 0 !important;
    cursor: pointer !important;
    transition: background 0.15s ease, border-color 0.15s ease !important;
    vertical-align: middle !important;
    box-shadow: none !important;
    color: {_t_icon_fg} !important;
    opacity: 1 !important;
}}
button[data-testid="stTooltipHoverTarget"]:hover,
button[data-testid="stTooltipIcon"]:hover {{
    background: {_t_icon_bg_h} !important;
    border-color: {_t_icon_fg_h} !important;
    color: {_t_icon_fg_h} !important;
}}
/* SVG — taille 16px, couleur héritée du bouton */
button[data-testid="stTooltipHoverTarget"] svg,
button[data-testid="stTooltipIcon"] svg {{
    width: 16px !important;
    height: 16px !important;
    overflow: visible !important;
    color: inherit !important;
}}
/* Masquer le <circle> intégré au SVG — le bouton joue déjà le rôle du cercle.
   Sans cela, le SVG stroke-based dessine un 2e cercle par-dessus le rond CSS. */
button[data-testid="stTooltipHoverTarget"] svg circle,
button[data-testid="stTooltipIcon"] svg circle {{
    display: none !important;
}}
/* Forcer la couleur du glyphe ? (path + point) — stroke ET fill pour les 2 variantes */
button[data-testid="stTooltipHoverTarget"] svg path,
button[data-testid="stTooltipIcon"] svg path,
button[data-testid="stTooltipHoverTarget"] svg line,
button[data-testid="stTooltipIcon"] svg line {{
    stroke: currentColor !important;
    fill: none !important;
}}
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
## DATA LOADING
# ===========================================================

@st.cache_data(ttl=20)
def _get_recent_decisions(n: int = 50, asset: str | None = None) -> list[dict]:
    """20s cache - V7 decisions from dag_logs (fallback to the V1 decisions table)."""
    try:
        from storage.database import get_connection
        with get_connection() as conn:
            if asset:
                rows = conn.execute(
                    "SELECT ts, level, dag_id, node_id, message FROM dag_logs "
                    "WHERE message LIKE ? ORDER BY ts DESC LIMIT ?",
                    (f"%[{asset}]%", n),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT ts, level, dag_id, node_id, message FROM dag_logs "
                    "ORDER BY ts DESC LIMIT ?", (n,)
                ).fetchall()
            if rows:
                import re as _re
                results = []
                for r in rows:
                    msg = r["message"] or ""
                    sym_match = _re.search(r'\[([A-Z]+)/USDT\]', msg)
                    results.append({
                        "symbol": sym_match.group(1) + "/USDT" if sym_match else (asset or "?"),
                        "action": "carry" if "HOLD" in msg else ("flat" if "FLAT" in msg else "?"),
                        "timestamp": r["ts"],
                        "reason": msg,
                    })
                return results
            # Fallback: the old decisions table (V1)
            from storage.database import get_recent_decisions as _legacy
            return _legacy(n, asset=asset)
    except Exception:
        return []


@st.cache_data(ttl=90)
def _get_live_indicators(asset: str) -> dict:
    """Live indicators with a 90s cache - queries the V4 API for prices."""
    try:
        import urllib.request, json
        req = urllib.request.Request(f"{_API_BASE}/prices/snapshot?asset={asset}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception:
        return {}


@st.cache_data(ttl=120)
def _get_ohlcv(asset: str) -> tuple[list, list]:
    """OHLCV 15m / 24h with a 2min cache - avoids a blocking fetch_ohlcv on every rerun."""
    try:
        import ccxt
        exchange = ccxt.binance()
        ohlcv = exchange.fetch_ohlcv(asset, timeframe="15m", limit=96)
        return [row[0] for row in ohlcv], [row[4] for row in ohlcv]
    except Exception:
        try:
            import json, urllib.request as _ur
            _YF_MAP = {"XAU/USD": "GC=F", "EUR/USD": "EURUSD=X",
                       "GBP/USD": "GBPUSD=X", "USD/JPY": "JPY=X"}
            ticker = _YF_MAP.get(asset, asset)
            req = _ur.Request(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
                f"?interval=15m&range=1d&includePrePost=false",
                headers={"User-Agent": "atlas-trader/2.0"},
            )
            with _ur.urlopen(req, timeout=15) as _r:
                _yf = json.loads(_r.read())
            _res = _yf["chart"]["result"][0]
            times  = [t * 1000 for t in _res["timestamp"]]
            raw_c  = _res["indicators"]["quote"][0].get("close", [])
            closes = [c for c in raw_c if c is not None]
            return times, closes
        except Exception:
            return [], []


@st.cache_data(ttl=30)
def _get_recent_trades(n: int = 200, asset: str | None = None) -> list[dict]:
    """Return the recent trades: V4 DB (preferred) + V3 DB fallback."""
    trades: list[dict] = []

    # 1) V4 trades from the DB (persistent, not tied to the cycle)
    try:
        from storage.paper_trader import get_v4_trades
        v4_trades = get_v4_trades(n=n, symbol=asset)
        # NB: the loop variable is named 'tr', not 't' - 't' is the i18n function
        for tr in v4_trades:
            # Extract the carry context (funding, score, etc.)
            _score = 0
            _total_funding = 0.0
            _n_payments = 0
            _ctx_raw = tr.get("context_json")
            if _ctx_raw:
                try:
                    import json as _json
                    _ctx = _json.loads(_ctx_raw) if isinstance(_ctx_raw, str) else _ctx_raw
                    _score = int(_ctx.get("score", 0))
                    _total_funding = float(_ctx.get("total_funding_received", 0) or 0)
                    _n_payments = int(_ctx.get("n_payments", 0) or 0)
                except Exception:
                    pass
            trades.append({
                "id": f"{tr.get('dag_id','v4')}_{tr.get('symbol','')}_{tr.get('trade_id','')}",
                "timestamp": tr.get("timestamp", ""),
                "asset": tr.get("symbol", ""),
                "action": "CARRY" if tr.get("action") in ("carry", "short") else ("BUY" if tr.get("action") == "long" else "SELL"),
                "entry_price": tr.get("entry_price"),
                "sl_price": tr.get("stop_loss", 0),
                "tp_price": tr.get("take_profit", 0),
                "position_size": tr.get("size_usd", 0),
                "result_24h": tr.get("pnl_usd") if tr.get("status") == "closed" else None,
                "status": tr.get("status", "open"),
                "source": "v4",
                "score": _score,
                "total_funding_received": _total_funding,
                "n_payments": _n_payments,
            })
    except Exception:
        pass

    trades.sort(key=lambda tr: str(tr.get("timestamp", "")), reverse=True)
    return trades[:n]


@st.cache_data(ttl=30)
def _get_portfolio(asset: str | None = None) -> dict:
    """Consolidated portfolio - open positions + cumulative PnL from the DB."""
    portfolio = {"capital": 10000, "current_value": 10000, "total_pnl": 0,
                 "total_pnl_pct": 0, "n_trades": 0, "asset": asset or "ALL",
                 "live_mode": False, "exposure": 0, "exposure_pct": 0}

    # V4: open positions + cumulative PnL from the DB
    try:
        from storage.paper_trader import get_v4_trades
        all_trades = get_v4_trades(n=500, symbol=asset)
        total_pnl = 0.0
        n_open = 0
        total_exposure = 0.0
        for tr in all_trades:
            if tr.get("status") == "open":
                n_open += 1
                total_exposure += float(tr.get("size_usd", 0) or 0)
            pnl = tr.get("pnl_usd")
            if pnl is not None:
                total_pnl += float(pnl)
        portfolio["n_trades"] = n_open
        portfolio["exposure"] = round(total_exposure, 2)
        portfolio["total_pnl"] = round(total_pnl, 2)
        if portfolio["capital"] > 0:
            portfolio["total_pnl_pct"] = round(total_pnl / portfolio["capital"] * 100, 2)
            portfolio["exposure_pct"] = round(total_exposure / portfolio["capital"] * 100, 2)
    except Exception:
        pass

    return portfolio


@st.cache_data(ttl=30)
def _get_pnl_history() -> list[dict]:
    try:
        from storage.database import get_pnl_history
        return get_pnl_history()
    except Exception:
        return []


@st.cache_data(ttl=30)
def _get_last_cycle() -> dict | None:
    decisions = _get_recent_decisions(1)
    return decisions[0] if decisions else None


@st.cache_data(ttl=60)
def _carry_asset_list() -> list[str]:
    """Actifs configurés dans carry_assets.yaml — alimente les filtres du dashboard.

    Liste dynamique : une liste codée en dur divergeait de la config réelle
    (AVAX manquant, ADA/DOGE désactivés mais proposés).
    """
    try:
        from v7.core.asset_config import get_all_assets
        return get_all_assets() or []
    except Exception:
        return []


# ===========================================================
# COMPOSANTS UI USER
# ===========================================================

def _force_run_background(asset: str, log_q) -> None:
    """
    Déclenche un cycle Funding Carry immédiat via /carry/run (endpoint non bloquant).
    Poste des chaînes HTML dans log_q au fur et à mesure.
    Poste ("__done__", (is_error: bool, message: str)) en dernier.
    """
    import time as _time
    import logging

    _logger = logging.getLogger("atlas.workflow")

    def _log(txt):
        log_q.put(txt)

    start_ts = _time.strftime("%Y-%m-%d %H:%M:%S")
    _logger.info(f"=== DASHBOARD FORCE-RUN — {asset} @ {start_ts} ===")
    _log(f"🚀 <b>Funding carry cycle started</b> ({start_ts})")
    _log("⏳ Asset scan → funding → decisions → persistence…")

    t_total = _time.time()
    try:
        import urllib.request, json
        req = urllib.request.Request(
            f"{_API_BASE}/carry/run",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "launch refused"))

        _log("✅ <b>Cycle started</b> — reading the first logs…")

        # Let the cycle start, then show the recent carry logs
        _time.sleep(8)
        try:
            with urllib.request.urlopen(f"{_API_BASE}/dag/logs?n=40", timeout=10) as resp:
                rows = json.loads(resp.read())
            shown = 0
            for row in rows:
                if row.get("level") == "DEBUG":
                    continue
                msg = str(row.get("message", ""))[:150]
                _log(f"  • <b>{row.get('dag_id', '?')}</b> {msg}")
                shown += 1
                if shown >= 12:
                    break
            if shown == 0:
                _log("  <i>(no log yet - the cycle is starting)</i>")
        except Exception as _e:
            _log(f"  <i>(logs indisponibles : {str(_e)[:80]})</i>")

        total_s = _time.time() - t_total
        log_q.put(("__done__", (False, f"Cycle launched in the background ({total_s:.1f}s)")))

    except Exception as exc:
        total_s = _time.time() - t_total
        _logger.exception(f"Force-run failed: {exc}")
        _log(f"❌ <b>Cycle error</b> — {exc} ({total_s:.1f}s)")
        log_q.put(("__done__", (True, f"Error: {exc}")))


@st.dialog("⚡ Force Run", width="small")
def _force_run_dialog(asset: str):
    """
    Popup modale non-bloquante.
    - Au premier appel : acquiert le lock et démarre _force_run_background dans un thread daemon.
    - Aux appels suivants (via st.rerun() toutes les 0.5s) : draine la queue et affiche les logs.
    - Quand le thread termine : affiche le résultat final et libère les ressources.
    """
    import time as _time
    import threading as _threading
    import queue as _queue
    from utils.cycle_lock import try_acquire, release

    _KEY = "_frd_state"

    # -- First entry: acquire the lock and start the thread --
    if _KEY not in st.session_state:
        if not try_acquire(owner="dashboard-force"):
            from utils.cycle_lock import lock_info
            info = lock_info()
            if info:
                owner = info["owner"].replace("daemon-", "")
                st.warning(f"⏳ {t('run_already_running')} ({owner}, {info['age_s']}s)")
            else:
                st.warning(t("run_already_running"))
            st.session_state.pop("_force_run_asset", None)
            return

        log_q = _queue.Queue()

        def _bg():
            try:
                _force_run_background(asset, log_q)
            finally:
                release()

        thr = _threading.Thread(target=_bg, daemon=True, name="force_run_bg")
        thr.start()
        st.session_state[_KEY] = {"log_q": log_q, "logs": [], "final": None, "thread": thr}

    # ── CSS dialog : compact + scrollable ─────────────────────────────────
    st.markdown("""<style>
    [data-testid="stDialog"] [data-testid="stMarkdown"] p {
        font-size: 11px; line-height: 1.2; font-family: 'SFMono-Regular',Consolas,monospace;
        margin: 0; padding: 0;
    }
    [data-testid="stDialog"] [data-testid="stMarkdown"] { margin-bottom: -8px; }
    [data-testid="stDialog"] [data-testid="stVerticalBlock"] {
        max-height: 55vh; overflow-y: auto;
    }
    </style>""", unsafe_allow_html=True)

    # ── Drainer la queue des logs ────────────────────────────────────────────
    s = st.session_state[_KEY]
    try:
        while True:
            item = s["log_q"].get_nowait()
            if isinstance(item, tuple) and item[0] == "__done__":
                s["final"] = item[1]   # (is_error: bool, message: str)
            else:
                s["logs"].append(item)
    except _queue.Empty:
        pass

    # -- Show the accumulated logs --
    log_c = st.container()
    for msg in s["logs"]:
        log_c.markdown(msg, unsafe_allow_html=True)

    # -- Finished, or still running --
    if s["final"] is not None:
        is_error, msg = s["final"]
        st.divider()
        if is_error:
            st.error(msg)
        else:
            st.success(msg)
        st.session_state.pop(_KEY, None)
        st.session_state.pop("_force_run_asset", None)
        st.cache_data.clear()
    else:
        with st.spinner(""):
            _time.sleep(0.5)
        st.rerun()


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
            _logout()
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
        if st.session_state.get("admin_authenticated"):
            # The carry cycle covers every enabled asset (carry_assets.yaml)
            st.session_state["_force_run_asset"] = "ALL"
        # else: silently ignore — unauthenticated users cannot trigger a cycle

    if st.session_state.get("admin_authenticated") and st.session_state.get("_force_run_asset"):
        _force_run_dialog(st.session_state["_force_run_asset"])

    # ─ URLs ─────────────────────────────────────────────────────────────────
    adm   = "1" if show_admin else "0"
    _sid = st.query_params.get("_sid", "") or st.session_state.get("_session_id", "")
    sid_q = f"&_sid={_sid}" if _sid else ""
    # Keep _sid in the URLs to preserve the session across refresh/navigation
    m_open  = f"lang={lang_param}&theme={theme}&admin={adm}&menu=1{sid_q}"
    m_close = f"lang={lang_param}&theme={theme}&admin={adm}&menu=0{sid_q}"
    base    = f"lang={lang_param}&theme={theme}&admin={adm}&menu=0{sid_q}"
    u_refresh  = f"?_action=refresh&{base}"
    u_force    = f"?_action=force_run&{base}"
    u_hamburger = f"?{m_close if menu_open else m_open}"
    # menu items (each click closes the menu)
    u_admin    = f"?lang={lang_param}&theme={theme}&admin=1&menu=0{sid_q}"
    u_logout   = f"?_action=logout&{base}"
    u_t_light  = f"?lang={lang_param}&theme=light&admin={adm}&menu=0{sid_q}"
    u_t_dark   = f"?lang={lang_param}&theme=dark&admin={adm}&menu=0{sid_q}"
    u_t_system = f"?lang={lang_param}&theme=system&admin={adm}&menu=0{sid_q}"
    u_l_fr     = f"?lang=fr&theme={theme}&admin={adm}&menu=0{sid_q}"
    u_l_en     = f"?lang=en&theme={theme}&admin={adm}&menu=0{sid_q}"
    u_l_de     = f"?lang=de&theme={theme}&admin={adm}&menu=0{sid_q}"
    u_l_es     = f"?lang=es&theme={theme}&admin={adm}&menu=0{sid_q}"
    u_l_it     = f"?lang=it&theme={theme}&admin={adm}&menu=0{sid_q}"
    u_l_pt     = f"?lang=pt&theme={theme}&admin={adm}&menu=0{sid_q}"
    u_l_nl     = f"?lang=nl&theme={theme}&admin={adm}&menu=0{sid_q}"
    u_l_zh     = f"?lang=zh&theme={theme}&admin={adm}&menu=0{sid_q}"

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

    # ─ Cycle running? ─────────────────────────────────────────────────────
    # _cycle_locked: a cycle is ACTIVE right now (lock held)
    # _daemon_alive: daemon alive (heartbeat < 30 min) but not necessarily cycling
    from utils.cycle_lock import is_locked as _cycle_is_locked
    _cycle_locked = _cycle_is_locked()
    _daemon_alive = _cycle_locked
    if not _daemon_alive:
        # V2: check how old v2_state.updated_at is (< 30 min = daemon active)
        try:
            from storage.database import get_v2_state as _hb_v2s
            _v2st = _hb_v2s()
            if _v2st and _v2st.get("updated_at"):
                _v2_age = (datetime.utcnow() - datetime.fromisoformat(_v2st["updated_at"])).total_seconds()
                if _v2_age < 1800:
                    _daemon_alive = True
        except Exception:
            pass
    if not _daemon_alive:
        # Legacy V1 : fichiers heartbeat
        import glob as _hb_glob, os as _hb_os, time as _hb_time
        for _hbf in _hb_glob.glob("/tmp/atlas_heartbeat_*"):
            try:
                if _hb_time.time() - _hb_os.path.getmtime(_hbf) < 1800:
                    _daemon_alive = True
                    break
            except Exception:
                pass

    # ─ Styles helper ────────────────────────────────────────────────────────
    S_BTN = (f"text-decoration:none;border-radius:5px;padding:5px 11px;"
             f"font-size:16px;color:{nav_fg};white-space:nowrap;"
             f"display:inline-flex;align-items:center;height:32px;"
             f"background:rgba(128,128,128,0.13);")
    S_HBG_ON  = (f"text-decoration:none;border-radius:5px;padding:5px 10px;"
                 f"font-size:16px;color:{nav_fg};"
                 f"display:inline-flex;align-items:center;height:32px;"
                 f"background:rgba(255,75,75,0.25);")
    S_HBG_OFF = (f"text-decoration:none;border-radius:5px;padding:5px 10px;"
                 f"font-size:16px;color:{nav_fg};"
                 f"display:inline-flex;align-items:center;height:32px;"
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
    admin_label = f"{admin_icon}&nbsp; {t('hbg_admin')}"
    admin_bg    = f"background:rgba(255,75,75,0.18);" if show_admin else ""

    # -- HTML dropdown (rendered only when menu_open) --
    dropdown_html = ""
    if menu_open:
        _pill_light  = pill(u_t_light,  f'<i class="fas fa-sun"></i> {t("theme_light")}',      theme == "light")
        _pill_dark   = pill(u_t_dark,   f'<i class="fas fa-moon"></i> {t("theme_dark")}',       theme == "dark")
        _pill_system = pill(u_t_system, f'<i class="fas fa-desktop"></i> {t("theme_system")}',  theme == "system")
        dropdown_html = f"""
<div style="position:fixed;top:49px;right:8px;min-width:235px;
            z-index:9998;background:{dd_bg};
            border:1px solid {nav_bdr};border-radius:10px;
            box-shadow:0 6px 30px rgba(0,0,0,0.35);
            padding:6px 0;display:flex;flex-direction:column;">
  <a href="{u_admin}" style="text-decoration:none;display:block;padding:10px 16px;
     font-size:14px;color:{nav_fg};{admin_bg}" target="_blank">{admin_label}</a>
  <div style="{S_SEP}"></div>
  <div style="{S_LBL}"><i class="fas fa-palette" style="margin-right:5px;"></i>{t('hbg_theme')}</div>
  <div style="{S_ROW}">
    {_pill_light}
    {_pill_dark}
    {_pill_system}
  </div>
  <div style="{S_SEP}"></div>
  <div style="{S_LBL}"><i class="fas fa-globe" style="margin-right:5px;"></i>{t('hbg_lang')}</div>
  <div style="{S_ROW}">
    {pill(u_l_fr, '🇫🇷', lang_param == "fr")}
    {pill(u_l_en, '🇬🇧', lang_param == "en")}
    {pill(u_l_de, '🇩🇪', lang_param == "de")}
    {pill(u_l_es, '🇪🇸', lang_param == "es")}
    {pill(u_l_it, '🇮🇹', lang_param == "it")}
    {pill(u_l_pt, '🇵🇹', lang_param == "pt")}
    {pill(u_l_nl, '🇳🇱', lang_param == "nl")}
    {pill(u_l_zh, '🇨🇳', lang_param == "zh")}
  </div>
{f'''  <div style="{S_SEP}"></div>
  <a href="{u_logout}" style="text-decoration:none;display:block;padding:10px 16px;
     font-size:14px;color:{nav_fg};" target="_self">
    <i class="fas fa-right-from-bracket" style="margin-right:8px;opacity:0.7;"></i>
    {t("logout_btn")} &mdash; {st.session_state.get("username", "")}
  </a>''' if st.session_state.get('admin_authenticated') else ''}
</div>"""

    # ─ Rendu final ──────────────────────────────────────────────────────────
    # Auto-refresh every 15s while a cycle runs -> stops automatically when done
    st.markdown(f"""
<style>
header[data-testid="stHeader"]{{display:none!important;}}
.main .block-container,[data-testid="stMainBlockContainer"]{{padding-top:56px!important;padding-bottom:0!important;}}
[data-testid="stTabs"]{{margin-top:-1rem!important;}}
[data-testid="stMainBlockContainer"] > div:first-child {{gap:0!important;}}
@keyframes atlas-pulse {{
  0%,100% {{ opacity:1; }}
  50%     {{ opacity:0.35; }}
}}
.atlas-bolt-active {{
  animation: atlas-pulse 1.2s ease-in-out infinite !important;
  background: rgba(34,197,94,0.25) !important;
  color: #22c55e !important;
}}
.atlas-bolt-alive {{
  background: rgba(59,130,246,0.22) !important;
  color: #60a5fa !important;
}}
</style>
<nav style="position:fixed;top:0;left:0;right:0;height:48px;
            background:{nav_bg};z-index:9999;
            border-bottom:1px solid {nav_bdr};
            box-shadow:0 2px 10px rgba(0,0,0,0.24);
            display:flex;align-items:center;
            padding:0 1rem;gap:10px;box-sizing:border-box;">
  <a href="?lang={lang_param}&theme={theme}&admin=0&menu=0{sid_q}" target="_self"
     style="display:flex;align-items:center;flex-shrink:0;text-decoration:none;">
    <img src="data:image/png;base64,{_LOGO_B64}"
         style="height:32px;width:32px;border-radius:7px;object-fit:cover;"
         alt="Atlas">
  </a>
  <span style="flex:1;color:{nav_fg};font-weight:700;font-size:15px;
               white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
    Atlas Trader
  </span>
  <span style="font-size:12px;color:{nav_fg};opacity:0.6;white-space:nowrap;flex-shrink:0;font-variant-numeric:tabular-nums;">{_fmt_utc_local(datetime.utcnow())}</span>
  <a href="{u_refresh}" style="{S_BTN}" title="{t('hbg_refresh')}" target="_self"><i class="fas fa-rotate-right"></i></a>
  <a href="{u_hamburger}" style="{S_HBG}" title="Menu" target="_self"><i class="fas fa-bars"></i></a>
</nav>
{dropdown_html}
""", unsafe_allow_html=True)



def _card_colors(theme: str) -> tuple[str, str, str, str, str]:
    """(bg, border, text, muted, icon_color) for the current theme."""
    if theme == "light":
        return "#ffffff", "#dee2e6", "#212529", "#6c757d", "#5c73c0"
    return "#1b1f27", "rgba(255,255,255,0.1)", "#f0f0f0", "rgba(255,255,255,0.45)", "#7986cb"


def _html_card(fa: str, label: str, val_html: str,
               bg: str, bdr: str, txt: str, muted: str, ic: str,
               delta: str | None = None, d_pos: bool | None = None) -> str:
    """Build a Bootstrap-like card in pure HTML with a Font Awesome icon."""
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


def render_portfolio(portfolio: dict):
    """Paper portfolio as Bootstrap-like cards with Font Awesome."""
    theme   = _get_theme()
    pnl     = portfolio.get("total_pnl", 0)
    pnl_pct = portfolio.get("total_pnl_pct", 0)
    pnl_pos = pnl >= 0
    pnl_col = "#2ecc71" if pnl_pos else "#e74c3c"
    asset   = portfolio.get("asset", "ALL")
    is_live = portfolio.get("live_mode", False)

    mode_badge = (
        '<span style="font-size:10px;background:#e74c3c;color:#fff;border-radius:3px;'
        'padding:1px 5px;margin-left:6px;vertical-align:middle;">LIVE</span>'
        if is_live else
        '<span style="font-size:10px;background:#f39c12;color:#fff;border-radius:3px;'
        'padding:1px 5px;margin-left:6px;vertical-align:middle;">PAPER</span>'
    )
    asset_label = "" if asset == "ALL" else f" — {asset}"

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
        _html_card("fas fa-chart-pie", "💸 Exposure",
                   f'${portfolio.get("exposure", 0):,.0f}',
                   delta=f"{portfolio.get('exposure_pct', 0):.1f}% of capital", d_pos=None, **kw) +
        _html_card("fas fa-right-left", t("trades_label"),
                   str(portfolio.get("n_trades", 0)), **kw)
    )

    st.markdown(
        f'<h3 style="margin:0 0 10px;font-size:18px;">'
        f'<i class="fas fa-briefcase" style="margin-right:8px;color:#7986cb;"></i>'
        f'{t("portfolio_title")}{asset_label}{mode_badge}</h3>'
        f'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));'
        f'gap:12px;margin-bottom:16px;">{grid}</div>',
        unsafe_allow_html=True,
    )


@st.dialog("Decision Analysis", width="large")
def _show_trade_detail_dialog(trade: dict) -> None:
    """Modal: full logic + weight traceability for one trade."""
    import json as _json

    action = trade.get("action", "?")
    asset  = trade.get("asset", "?")
    ts     = (trade.get("timestamp") or "")[:16].replace("T", " ")
    pnl    = trade.get("result_24h")
    score  = trade.get("score")
    entry  = trade.get("entry_price")
    expl   = trade.get("explanation", "")

    color = "#2ecc71" if action == "BUY" else "#e74c3c"
    icon  = "▲" if action == "BUY" else "▼"

    # ── Header compact ──────────────────────────────────────────────────────────
    parts = [f"<b style='color:{color}'>{icon} {action}</b>", asset, ts + " UTC"]
    if entry:         parts.append(f"Entry <b>${float(entry):,.2f}</b>")
    size = trade.get("position_size_usd") or trade.get("position_size")
    if size is not None:
        parts.append(f"Size <b>${float(size):,.0f}</b>")
    if pnl is not None: parts.append(f"P&L <b style='color:{color}'>${float(pnl):+.2f}</b>")
    if score is not None: parts.append(f"Score <b>{float(score):.0f}/100</b>")
    st.markdown(
        "<div style='border-left:3px solid " + color + ";padding:5px 10px;"
        "border-radius:3px;font-size:13px;margin-bottom:8px'>"
        + "  ·  ".join(parts) + "</div>",
        unsafe_allow_html=True,
    )

    # -- Fetch the context --
    ctx: dict = {}
    raw_ctx = trade.get("decision_context")
    if raw_ctx:
        try:
            ctx = _json.loads(raw_ctx) if isinstance(raw_ctx, str) else raw_ctx
        except Exception:
            ctx = {}

    # ── Trades anciens ──────────────────────────────────────────────────────────
    if not ctx:
        st.caption(t("dialog_old_trade"))
        if expl:
            st.markdown(f"<div style='font-size:12px;line-height:1.6'>{expl}</div>",
                        unsafe_allow_html=True)
        return

    tab_formula, tab_agents, tab_mkt, tab_dec, tab_ia = st.tabs(
        [t("tab_formula"), t("tab_agents_dialog"), t("tab_market_dialog"), t("tab_decision"), t("tab_ai")]
    )

    # ── Tab Formule ─────────────────────────────────────────────────────────────
    # Shows the exact breakdown: score = sum(component x weight)
    with tab_formula:
        eff_w = ctx.get("effective_weights") or {}
        dec   = ctx.get("decision") or {}
        s_val = dec.get("score") if dec.get("score") is not None else score

        def _comp_row(comp: dict, name: str, label: str) -> str:
            if not isinstance(comp, dict):
                return ""
            sc = comp.get("score")
            w  = comp.get("weight")
            ct = comp.get("contribution")
            if sc is None or w is None:
                return ""
            bar_pct = min(100, max(0, float(sc)))
            bar_col = "#2ecc71" if float(sc) >= 60 else ("#e74c3c" if float(sc) < 40 else "#f39c12")
            fb = " <span style='opacity:.5;font-size:10px'>(fallback)</span>" if comp.get("fallback_mode") else ""
            return (
                f"<tr><td style='padding:5px 8px;font-size:12px;font-weight:600'>{label}{fb}</td>"
                f"<td style='padding:5px 8px;font-size:12px;text-align:right'>{float(sc):.1f}</td>"
                f"<td style='padding:5px 8px'>"
                f"<div style='width:100px;height:8px;background:rgba(128,128,128,.2);border-radius:4px;display:inline-block'>"
                f"<div style='width:{bar_pct:.0f}%;height:100%;background:{bar_col};border-radius:4px'></div></div></td>"
                f"<td style='padding:5px 8px;font-size:12px;text-align:right;opacity:.8'>× {float(w):.2f}</td>"
                f"<td style='padding:5px 8px;font-size:12px;text-align:right;font-weight:600;color:{bar_col}'>"
                f"= {float(ct):.2f} pts</td></tr>"
            )

        if eff_w:
            rows_html = ""
            rows_html += _comp_row(eff_w.get("mirofish", {}),   "mirofish",   "MiroFish (simulation)")
            rows_html += _comp_row(eff_w.get("market", {}),     "market",     "Market (technique)")
            rows_html += _comp_row(eff_w.get("agents", {}),     "agents",     "Agents (IA)")
            rows_html += _comp_row(eff_w.get("contrarian", {}), "contrarian", "Contrarian")
            final = f"{float(s_val):.1f}" if s_val is not None else "?"
            rows_html += (
                f"<tr style='border-top:2px solid rgba(128,128,128,.3)'>"
                f"<td colspan='4' style='padding:6px 8px;font-size:13px;font-weight:700'>Score final</td>"
                f"<td style='padding:6px 8px;font-size:16px;font-weight:700;color:{color}'>{final} / 100</td></tr>"
            )
            st.markdown(
                f"<table style='width:100%;border-collapse:collapse'>{rows_html}</table>",
                unsafe_allow_html=True,
            )

            # Per-agent detail inside the 'agents' component
            agents_comp = eff_w.get("agents", {})
            agent_weights_in_comp = agents_comp.get("agent_weights", {})
            agent_detail_scores   = agents_comp.get("detail", {})
            if agent_weights_in_comp or agent_detail_scores:
                st.markdown("---")
                st.caption("**Individual agent weights inside the AI component**")
                agt_ctx = ctx.get("agents") or {}
                all_names = set(agent_weights_in_comp) | set(agent_detail_scores)
                rows_agt = []
                for name in sorted(all_names):
                    w_ind  = agent_weights_in_comp.get(name)
                    sc_ind = agent_detail_scores.get(name)
                    sig    = (agt_ctx.get(name) or {}).get("signal", "—") if isinstance(agt_ctx.get(name), dict) else "—"
                    contrib = float(sc_ind) * float(w_ind) if sc_ind is not None and w_ind is not None else None
                    rows_agt.append({
                        "Agent":          name,
                        "Score":          f"{float(sc_ind):.0f}" if sc_ind is not None else "—",
                        "Signal":         sig,
                        "Poids (w_in_scoring)": f"{float(w_ind):.3f}" if w_ind is not None else "—",
                        "Contribution":   f"{contrib:.2f} pts" if contrib is not None else "—",
                    })
                st.dataframe(pd.DataFrame(rows_agt), hide_index=True, use_container_width=True)
        else:
            st.caption(t("formula_data_unavailable"))
            if s_val is not None:
                st.metric("Score", f"{float(s_val):.1f}/100")

    # ── Tab Agents ──────────────────────────────────────────────────────────────
    with tab_agents:
        agt   = ctx.get("agents") or {}
        eff_w = ctx.get("effective_weights") or {}
        agents_comp = eff_w.get("agents", {})
        agent_weights_in_comp = agents_comp.get("agent_weights", {}) if isinstance(agents_comp, dict) else {}

        if agt:
            sorted_agents = sorted(
                agt.items(),
                key=lambda x: float(x[1].get("score", 0)) if isinstance(x[1], dict) and x[1].get("score") is not None else 0,
                reverse=True,
            )
            for name, info in sorted_agents:
                if not isinstance(info, dict):
                    continue
                sc      = info.get("score")
                sig     = info.get("signal", "—")
                w       = agent_weights_in_comp.get(name)
                summary = info.get("summary") or ""

                sc_float  = float(sc) if sc is not None else 0.0
                bar_color = "#2ecc71" if sc_float >= 60 else ("#e74c3c" if sc_float < 40 else "#f39c12")
                contrib   = sc_float * float(w) if w is not None else None
                w_str     = f" · w={float(w):.3f}" + (f" → {contrib:.1f}pts" if contrib is not None else "") if w is not None else ""
                label     = f"{name}  {sc_float:.0f}/100 · {sig}{w_str}"

                with st.expander(label, expanded=False):
                    col_sc, col_txt = st.columns([1, 3])
                    with col_sc:
                        contrib_str = f"<div style='font-size:11px;opacity:.7'>Contrib : <b>{contrib:.2f} pts</b></div>" if contrib is not None else ""
                        st.markdown(
                            f"<div style='font-size:22px;font-weight:700;color:{bar_color}'>"
                            f"{sc_float:.0f}<span style='font-size:12px;opacity:.6'>/100</span></div>"
                            f"<div style='width:100%;height:5px;background:rgba(128,128,128,.2);border-radius:3px;margin:4px 0'>"
                            f"<div style='width:{sc_float:.0f}%;height:100%;background:{bar_color};border-radius:3px'></div></div>"
                            f"<div style='font-size:11px;opacity:.7'>Signal : <b>{sig}</b></div>"
                            + (f"<div style='font-size:11px;opacity:.7'>Poids : <b>{float(w):.3f}</b></div>" if w is not None else "")
                            + contrib_str,
                            unsafe_allow_html=True,
                        )
                    with col_txt:
                        if summary:
                            st.markdown(
                                f"<div style='font-size:12px;line-height:1.5'>{summary}</div>",
                                unsafe_allow_html=True,
                            )
                        else:
                            st.caption(t("agent_summary_unavailable"))
        else:
            st.caption(t("agent_scores_unavailable"))

    # -- Market tab --
    with tab_mkt:
        mkt = ctx.get("market") or {}
        rgm = ctx.get("regime") or {}
        if not isinstance(rgm, dict):
            rgm = {"state": str(rgm)}

        if rgm:
            c1, c2, c3 = st.columns(3)
            c1.metric("Regime", str(rgm.get("state", rgm.get("hmm_regime", "—"))))
            hmm_p = rgm.get("hmm_prob")
            c2.metric("Prob. HMM", f"{float(hmm_p):.1%}" if hmm_p is not None else "—")
            c3.metric("Direction", str(rgm.get("direction_pressure", "—")))

        if mkt:
            st.markdown("---")
            mkt_items = [(k, v) for k, v in mkt.items() if v is not None]
            for chunk_start in range(0, len(mkt_items), 4):
                chunk = mkt_items[chunk_start:chunk_start + 4]
                cols = st.columns(len(chunk))
                for i, (k, v) in enumerate(chunk):
                    cols[i].metric(k, f"{float(v):.4f}" if isinstance(v, float) else str(v))
        else:
            st.caption(t("market_indicators_unavailable"))

    # -- Decision tab --
    with tab_dec:
        dec   = ctx.get("decision") or {}
        s_val = dec.get("score") if dec.get("score") is not None else score
        buy_thr  = dec.get("buy_threshold", "—")
        exit_thr = dec.get("exit_threshold", "—")

        c1, c2, c3 = st.columns(3)
        c1.metric("Score final", f"{float(s_val):.1f}/100" if s_val is not None else "—")
        c2.metric("BUY threshold", str(buy_thr))
        c3.metric("SELL threshold", str(exit_thr))

        reasoning = dec.get("reasoning", "")
        if reasoning:
            st.markdown("---")
            st.code(reasoning, language=None)

        blockers = []
        if dec.get("ma50_blocked"):    blockers.append("🚫 MA50")
        if dec.get("funding_blocked"): blockers.append("🚫 Funding rate")
        if dec.get("cooldown"):        blockers.append("⏸ Cooldown")
        if blockers:
            st.warning(t("blocked_prefix") + "  |  ".join(blockers))

    # ── Tab IA ──────────────────────────────────────────────────────────────────
    with tab_ia:
        if expl:
            st.markdown(
                f"<div style='font-size:12px;line-height:1.6'>{expl}</div>",
                unsafe_allow_html=True,
            )
        else:
            st.caption(t("ai_explanation_unavailable"))

        # -- Bull/Bear debate (when available in decision_context) --
        _synth_ctx = (ctx.get("agents") or {}).get("synthesis") or {}
        _dlg_sig_detail  = _synth_ctx.get("signal_detail")
        _dlg_debate_win  = _synth_ctx.get("debate_winner")
        _dlg_bull        = _synth_ctx.get("bull_argument")
        _dlg_bear        = _synth_ctx.get("bear_argument")

        if _dlg_sig_detail:
            _dsig_colors = {
                "STRONG_BUY":  ("rgba(27,94,32,0.25)",  "#69f0ae"),
                "BUY":         ("rgba(27,94,32,0.15)",  "#a5d6a7"),
                "HOLD":        ("rgba(255,152,0,0.15)", "#ffb74d"),
                "SELL":        ("rgba(183,28,28,0.15)", "#ef9a9a"),
                "STRONG_SELL": ("rgba(183,28,28,0.25)", "#e53935"),
            }
            _dbg, _dfg = _dsig_colors.get(_dlg_sig_detail, ("rgba(80,80,80,0.2)", "#ccc"))
            st.markdown(
                f"<div style='margin-top:10px;'>"
                f"<span style='background:{_dbg};color:{_dfg};"
                f"padding:3px 12px;border-radius:4px;font-size:12px;font-weight:700;"
                f"border:1px solid {_dfg}40;'>📊 Signal LLM : {_dlg_sig_detail}</span></div>",
                unsafe_allow_html=True,
            )

        if _dlg_bull and _dlg_bear and _dlg_bull not in ("[debate skipped]", "[debate unavailable]"):
            st.markdown("---")
            st.markdown("**🥊 Bull/Bear debate**")
            if _dlg_debate_win:
                _dw_clr = "#69f0ae" if "BULL" in str(_dlg_debate_win).upper() else ("#e53935" if "BEAR" in str(_dlg_debate_win).upper() else "#ffb74d")
                st.markdown(
                    f"<div style='margin-bottom:8px;font-size:12px;'>"
                    f"Vainqueur : <span style='color:{_dw_clr};font-weight:700;'>{_dlg_debate_win}</span></div>",
                    unsafe_allow_html=True,
                )
            _db_col1, _db_col2 = st.columns(2)
            with _db_col1:
                st.markdown("<div style='font-size:11px;font-weight:700;color:#69f0ae;'>🟢 Bull</div>", unsafe_allow_html=True)
                st.markdown(
                    f"<div style='font-size:11px;line-height:1.5;background:rgba(27,94,32,0.1);"
                    f"padding:6px;border-radius:4px;border-left:3px solid #69f0ae40;'>{_dlg_bull}</div>",
                    unsafe_allow_html=True,
                )
            with _db_col2:
                st.markdown("<div style='font-size:11px;font-weight:700;color:#e53935;'>🔴 Bear</div>", unsafe_allow_html=True)
                st.markdown(
                    f"<div style='font-size:11px;line-height:1.5;background:rgba(183,28,28,0.1);"
                    f"padding:6px;border-radius:4px;border-left:3px solid #e5393540;'>{_dlg_bear}</div>",
                    unsafe_allow_html=True,
                )



@st.fragment
def render_pnl_chart(history: list[dict], key: str = "pnl_chart"):
    """Cumulative performance chart."""
    st.markdown(f'<h3 style="margin:0 0 12px;font-size:18px;"><i class="fas fa-chart-area" style="margin-right:8px;color:#7986cb;"></i>{t("perf_chart_title")}</h3>', unsafe_allow_html=True)

    if not history:
        st.info(t("no_perf_data"))
        return

    df = pd.DataFrame(history)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    # V4 trades have no result_24h - default to 0
    if "result_24h" in df.columns:
        df["cumulative_pnl"] = df["result_24h"].fillna(0).cumsum()
    else:
        df["cumulative_pnl"] = 0
    final_pnl = df["cumulative_pnl"].iloc[-1] if len(df) > 0 else 0
    color = "#2ecc71" if final_pnl >= 0 else "#e74c3c"

    fig = go.Figure()
    # Courbe P&L
    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=df["cumulative_pnl"],
        fill="tozeroy",
        fillcolor=f"rgba({'0,200,100' if final_pnl >= 0 else '200,50,50'}, 0.15)",
        line=dict(color=color, width=2),
        name=t("chart_pnl_name"),
        yaxis="y1"
    ))
    # Prix BTC en overlay si disponible
    if "entry_price" in df.columns and df["entry_price"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["entry_price"],
            line=dict(color="#f39c12", width=1, dash="dot"),
            name=t("chart_btc_price"),
            yaxis="y2", opacity=0.6
        ))
    # BUY/SELL markers with the decision context in a tooltip
    if "action" in df.columns:
        buys = df[df["action"] == "BUY"]
        sells = df[df["action"] == "SELL"]

        def _build_ctx(row: dict, hist_idx: int) -> list:
            """Extract the key decision_context fields for the Plotly customdata."""
            import json as _json
            pnl = row.get("result_24h")
            entry = row.get("entry_price")
            asset_name = row.get("asset", "—") or "—"
            ctx_raw = row.get("decision_context")
            rsi, macd, regime, score, reasoning, agents_txt = "—", "—", "—", "—", "—", "—"
            # score fallback: always available as top-level column
            score_fallback = row.get("score")
            if score_fallback is not None:
                score = f"{float(score_fallback):.1f}"
            if ctx_raw:
                try:
                    ctx = _json.loads(ctx_raw) if isinstance(ctx_raw, str) else ctx_raw
                    mkt = ctx.get("market", {}) or {}
                    rgm = ctx.get("regime", {}) or {}
                    if not isinstance(rgm, dict):
                        rgm = {"state": str(rgm)}
                    dec = ctx.get("decision", {}) or {}
                    agt = ctx.get("agents", {}) or {}
                    rsi_v = mkt.get("rsi")
                    macd_v = mkt.get("macd_signal", mkt.get("macd"))
                    score_v = dec.get("score") if dec.get("score") is not None else score_fallback
                    rsi = f"{float(rsi_v):.1f}" if rsi_v is not None else "—"
                    macd = f"{float(macd_v):.4f}" if macd_v is not None else "—"
                    score = f"{float(score_v):.1f}" if score_v is not None else score
                    reasoning = str(dec.get("reasoning", "—"))[:160]
                    regime = str(rgm.get("regime", rgm.get("hmm_regime", "—")))
                    parts = [
                        f"{n}: {float(i.get('score', 0)):.0f}"
                        for n, i in agt.items()
                        if isinstance(i, dict) and i.get("score") is not None
                    ]
                    agents_txt = " | ".join(parts[:4]) if parts else "—"
                except Exception:
                    pass
            return [
                asset_name,   # [0]
                f"${float(pnl):+.2f}" if pnl is not None else "—",  # [1]
                f"${float(entry):,.2f}" if entry is not None else "—",  # [2]
                score,        # [3]
                regime,       # [4]
                rsi,          # [5]
                macd,         # [6]
                agents_txt,   # [7]
                reasoning,    # [8]
                hist_idx,     # [9] <- index in history[] for the dialog
            ]

        _hover_buy = (
            "<b>▲ BUY — %{customdata[0]}</b><br>"
            "Date : %{x|%Y-%m-%d %H:%M}<br>"
            "Cumulative P&L: %{y:+.2f}$<br>"
            "Entry : %{customdata[2]}<br>"
            "Score: %{customdata[3]} | Regime: %{customdata[4]}<br>"
            "RSI : %{customdata[5]} | MACD : %{customdata[6]}<br>"
            "Agents : %{customdata[7]}<br>"
            "<i style='opacity:0.6'>🖱 Click for the full detail</i>"
            "<extra></extra>"
        )
        _hover_sell = (
            "<b>▼ SELL — %{customdata[0]}</b><br>"
            "Date : %{x|%Y-%m-%d %H:%M}<br>"
            "Cumulative P&L: %{y:+.2f}$<br>"
            "P&L position : %{customdata[1]}<br>"
            "Entry : %{customdata[2]}<br>"
            "Score: %{customdata[3]} | Regime: %{customdata[4]}<br>"
            "RSI : %{customdata[5]} | MACD : %{customdata[6]}<br>"
            "Agents : %{customdata[7]}<br>"
            "<i style='opacity:0.6'>🖱 Click for the full detail</i>"
            "<extra></extra>"
        )

        if not buys.empty:
            buy_ctx = [_build_ctx(r, int(i)) for r, i in zip(buys.to_dict("records"), buys.index)]
            fig.add_trace(go.Scatter(
                x=buys["timestamp"], y=buys["cumulative_pnl"],
                mode="markers", marker=dict(symbol="triangle-up", size=12, color="#2ecc71"),
                name="BUY", yaxis="y1",
                customdata=buy_ctx,
                hovertemplate=_hover_buy,
            ))
        if not sells.empty:
            sell_ctx = [_build_ctx(r, int(i)) for r, i in zip(sells.to_dict("records"), sells.index)]
            fig.add_trace(go.Scatter(
                x=sells["timestamp"], y=sells["cumulative_pnl"],
                mode="markers", marker=dict(symbol="triangle-down", size=12, color="#e74c3c"),
                name="SELL", yaxis="y1",
                customdata=sell_ctx,
                hovertemplate=_hover_sell,
            ))
    fig.update_layout(
        height=340, margin=dict(l=0, r=0, t=20, b=0),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(gridcolor="rgba(128,128,128,0.2)"),
        yaxis=dict(gridcolor="rgba(128,128,128,0.2)", tickprefix="$", title="P&L"),
        yaxis2=dict(overlaying="y", side="right", showgrid=False,
                    tickprefix="$", title="BTC", tickfont=dict(color="#f39c12")),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
        clickmode="event+select",
    )
    event = st.plotly_chart(
        fig, use_container_width=True, key=key,
        on_select="rerun", selection_mode=["points"],
    )
    # Open the dialog when a BUY/SELL marker is clicked
    try:
        pts = (event.selection or {}).get("points") or []
    except Exception:
        pts = []
    if pts:
        pt = pts[0] if isinstance(pts[0], dict) else vars(pts[0])
        cd = pt.get("customdata") or []
        if len(cd) > 9:
            try:
                hist_idx = int(cd[9])
                if 0 <= hist_idx < len(history):
                    _show_trade_detail_dialog(history[hist_idx])
            except Exception:
                pass


def render_trades_list_sortable(trades: list[dict]):
    """Global trade history - automatic dark/light theme."""
    st.markdown(
        f'<h3 style="margin:16px 0 12px;font-size:18px;">'
        f'<i class="fas fa-clock-rotate-left" style="margin-right:8px;color:#7986cb;"></i>'
        f'{t("trades_all_title")}</h3>',
        unsafe_allow_html=True,
    )
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

    col_date   = t("col_date")
    col_asset  = t("col_asset")
    col_action = t("col_action")
    col_entry  = t("col_entry")
    col_size   = t("col_size_usd")
    col_pnl    = t("col_pnl")
    col_score  = t("col_score")

    # Live prices for the unrealised P&L
    live_prices: dict[str, float] = {}
    try:
        import urllib.request as _ur, json as _js
        req = _ur.Request(f"{_API_BASE}/prices/snapshot")
        with _ur.urlopen(req, timeout=3) as resp:
            prices_data = _js.loads(resp.read())
        for sym, data in prices_data.items():
            if isinstance(data, dict):
                live_prices[sym] = float(data.get("price", 0))
    except Exception:
        pass

    import json as _json_tr
    cols = [col_date, col_asset, col_action, "Signal", col_entry, col_size, "SL", "TP", col_pnl, "Funding", "Progression", col_score]
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

        # Extraire signal_detail
        _sig_detail = ""
        _raw_dc = trade.get("decision_context")
        if _raw_dc:
            try:
                _dc = _json_tr.loads(_raw_dc) if isinstance(_raw_dc, str) else _raw_dc
                _sig_detail = ((_dc.get("agents") or {}).get("synthesis") or {}).get("signal_detail") or ""
            except Exception:
                pass

        # Couleurs action
        if action == "BUY":
            action_html = f'<span style="color:#2ecc71;font-weight:bold;">BUY</span>'
        elif action == "SELL":
            action_html = f'<span style="color:#e74c3c;font-weight:bold;">SELL</span>'
        else:
            action_html = f'<span style="color:{tbl_fg};">{action}</span>'

        # Couleur Signal
        if _sig_detail in ("STRONG_BUY",):
            sig_html = f'<span style="color:#00e676;font-weight:700;">{_sig_detail}</span>'
        elif _sig_detail in ("BUY",):
            sig_html = f'<span style="color:#69f0ae;">{_sig_detail}</span>'
        elif _sig_detail in ("HOLD",):
            sig_html = f'<span style="color:#ffb74d;">{_sig_detail}</span>'
        elif _sig_detail in ("SELL",):
            sig_html = f'<span style="color:#ef9a9a;">{_sig_detail}</span>'
        elif _sig_detail in ("STRONG_SELL",):
            sig_html = f'<span style="color:#e53935;font-weight:700;">{_sig_detail}</span>'
        else:
            sig_html = f'<span style="opacity:0.4;">{_sig_detail or "—"}</span>'

        # PnL
        try:
            pnl_val = float(pnl) if pnl is not None else None
        except (ValueError, TypeError):
            pnl_val = None
        if pnl_val is None:
            pnl_str = f'<span style="opacity:.45;">{t("pending")}</span>'
        elif pnl_val >= 0:
            pnl_str = f'<span style="color:#2ecc71;font-weight:600;">${pnl_val:+,.2f}</span>'
        else:
            pnl_str = f'<span style="color:#e74c3c;font-weight:600;">${pnl_val:+,.2f}</span>'

        # Funding (open CARRY - actually collected, static)
        funding_str = "—"
        # Progression (P&L latent — live via JS)
        progress_str = "—"
        entry_price = trade.get("entry_price", 0) or 0
        size_usd = trade.get("position_size_usd") or trade.get("position_size") or 0
        current_price = live_prices.get(trade.get("asset", ""), 0)
        is_open = pnl_val is None
        _tid = trade.get("id", f"t{i}")
        _ast = trade.get("asset", "")
        if is_open:
            total_funding = float(trade.get("total_funding_received", 0) or 0)
            n_payments = int(trade.get("n_payments", 0) or 0)
            if action == "CARRY":
                # Days held
                try:
                    from datetime import datetime as _dt, timezone as _tz
                    _ts_str = str(trade.get("timestamp", "")).replace(" ", "T")[:19]
                    if _ts_str:
                        opened = _dt.fromisoformat(_ts_str)
                        days_held = max(0, (_dt.now(_tz.utc) - opened.replace(tzinfo=_tz.utc)).total_seconds() / 86400)
                    else:
                        days_held = 0
                except Exception:
                    days_held = 0
                if total_funding > 0:
                    funding_str = f'<span style="color:#2ecc71;font-size:11px;">💰 ${total_funding:.4f} ({n_payments}p × {days_held:.0f}d)</span>'
                else:
                    funding_str = f'<span style="color:#f39c12;font-size:11px;">⏳ {days_held:.0f}j · wait funding</span>'
                # Real unrealised P&L (basis + funding), filled in by the JS via /v7/carry-pnl
                progress_str = f'<span id="aprog-{_tid}" data-atlas-symbol="{_ast}" data-atlas-entry="{entry_price}" data-atlas-size="{size_usd}" data-atlas-action="{action}" data-atlas-open="1" style="opacity:.45;">—</span>'
            elif entry_price > 0 and current_price > 0 and size_usd > 0:
                if action in ("SELL", "SHORT"):
                    pnl_pct = (entry_price - current_price) / entry_price * 100
                else:
                    pnl_pct = (current_price - entry_price) / entry_price * 100
                unrealized = size_usd * pnl_pct / 100
                prog_color = "#2ecc71" if unrealized >= 0 else "#e74c3c"
                progress_str = f'<span id="aprog-{_tid}" data-atlas-symbol="{_ast}" data-atlas-entry="{entry_price}" data-atlas-size="{size_usd}" data-atlas-action="{action}" data-atlas-open="1" style="color:{prog_color};">{unrealized:+,.2f}$ ({pnl_pct:+.2f}%)</span>'
            else:
                progress_str = f'<span id="aprog-{_tid}" data-atlas-symbol="{_ast}" data-atlas-entry="{entry_price}" data-atlas-size="{size_usd}" data-atlas-action="{action}" data-atlas-open="1" style="opacity:.45;">—</span>'

        cells = [
            trade.get("timestamp", "")[:16].replace("T", " "),
            trade.get("asset", "—"),
            action_html,
            sig_html,
            f'${trade.get("entry_price", 0):,.2f}' if trade.get("entry_price") else "—",
            f'${(trade.get("position_size_usd") if trade.get("position_size_usd") is not None else trade.get("position_size", 0)):,.0f}'
                if (trade.get("position_size_usd") is not None or trade.get("position_size")) else "—",
            f'${trade.get("sl_price", 0):,.2f}' if trade.get("sl_price") else "—",
            f'${trade.get("tp_price", 0):,.2f}' if trade.get("tp_price") else "—",
            pnl_str,
            funding_str,
            progress_str,
            f'{trade.get("score", 0):.0f}/100',
        ]
        td_style = (f'padding:8px 12px;font-size:13px;color:{tbl_fg};'
                    f'white-space:nowrap;border-bottom:1px solid {sep};')
        tds = "".join(f'<td style="{td_style}">{c}</td>' for c in cells)
        rows_html += f'<tr style="background:{bg};">{tds}</tr>'

    # -- Summary row --
    _sum_realized = 0.0
    _sum_unrealized = 0.0
    _sum_funding = 0.0
    _n_closed = 0
    _n_open = 0
    _has_carry = False
    for trade in trades:
        # Closed P&L
        try:
            pnl = float(trade.get("result_24h") or 0)
        except (ValueError, TypeError):
            pnl = 0.0
        if trade.get("result_24h") is not None:
            _sum_realized += pnl
            _n_closed += 1
        else:
            # Unrealised P&L (open) - same computation as the Progression column
            entry_price = trade.get("entry_price", 0) or 0
            size_usd = trade.get("position_size_usd") or trade.get("position_size") or 0
            current_price = live_prices.get(trade.get("asset", ""), 0)
            act = trade.get("action", "")
            tfund = float(trade.get("total_funding_received", 0) or 0)
            if act == "CARRY":
                # Actually collected funding (static) + unrealised P&L ~ funding (server proxy,
                # replaced by the JS via /v7/carry-pnl with the real basis+funding)
                _has_carry = True
                _sum_funding += tfund
                _sum_unrealized += tfund
            elif entry_price > 0 and current_price > 0 and size_usd > 0:
                if act in ("SELL", "SHORT"):
                    pnl_pct = (entry_price - current_price) / entry_price
                else:
                    pnl_pct = (current_price - entry_price) / entry_price
                _sum_unrealized += size_usd * pnl_pct
            _n_open += 1

    _total_pnl = _sum_realized + _sum_unrealized
    _sum_color = "#2ecc71" if _total_pnl >= 0 else "#e74c3c"
    # Compute the total unrealised %
    _total_size = sum(
        (t.get("position_size_usd") or t.get("position_size") or 0)
        for t in trades if t.get("result_24h") is None
    )
    _total_unreal_pct = (_sum_unrealized / _total_size * 100) if _total_size > 0 else 0

    _sum_td = (
        # Col 1-3: TOTAL label
        f'<td style="padding:8px 12px;font-size:13px;font-weight:700;color:{tbl_fg};'
        f'white-space:nowrap;border-top:2px solid {border};background:{head_bg};" colspan="3">'
        f'{t("trades_summary_line").format(n=len(trades), closed=_n_closed, open=_n_open)}</td>'
        # Col 4: Signal (empty)
        f'<td style="padding:8px 12px;font-size:13px;color:{tbl_fg};white-space:nowrap;'
        f'border-top:2px solid {border};background:{head_bg};"></td>'
        # Col 5: Entry (empty)
        f'<td style="padding:8px 12px;font-size:13px;color:{tbl_fg};white-space:nowrap;'
        f'border-top:2px solid {border};background:{head_bg};"></td>'
        # Col 6: Size (total size)
        f'<td style="padding:8px 12px;font-size:13px;font-weight:600;color:{tbl_fg};'
        f'white-space:nowrap;border-top:2px solid {border};background:{head_bg};">${_total_size:,.0f}</td>'
        # Col 7-8: SL/TP (empty)
        f'<td style="padding:8px 12px;font-size:13px;color:{tbl_fg};white-space:nowrap;'
        f'border-top:2px solid {border};background:{head_bg};" colspan="2">—</td>'
        # Col 9: P&L (realized if any)
        f'<td style="padding:8px 12px;font-size:13px;color:{tbl_fg};white-space:nowrap;'
        f'border-top:2px solid {border};background:{head_bg};">{"${:+,.2f}".format(_sum_realized) if _n_closed > 0 else "—"}</td>'
        # Col 10: Funding total (statique)
        f'<td id="atlas-summary-funding" style="padding:8px 12px;font-size:13px;font-weight:600;color:#2ecc71;'
        f'white-space:nowrap;border-top:2px solid {border};background:{head_bg};">{"💰 ${:.4f}".format(_sum_funding) if _sum_funding > 0 else "—"}</td>'
        # Col 11: Progression (TOTAL latent $ + %)
        f'<td id="atlas-summary-prog" style="padding:8px 12px;font-size:13px;font-weight:700;color:{_sum_color};'
        f'white-space:nowrap;border-top:2px solid {border};background:{head_bg};">${_sum_unrealized:+,.2f} ({_total_unreal_pct:+.2f}%)</td>'
        # Col 12: Score (empty)
        f'<td style="padding:8px 12px;font-size:13px;color:{tbl_fg};white-space:nowrap;'
        f'border-top:2px solid {border};background:{head_bg};"></td>'
    )
    rows_html += f'<tr style="background:{head_bg};">{_sum_td}</tr>'

    html = f"""
<div style="overflow-y:auto;max-height:520px;border:1px solid {border};
            border-radius:10px;background:{tbl_bg};margin-bottom:24px;">
  <table style="border-collapse:collapse;width:100%;min-width:1100px;">
    <thead><tr>{header_cells}</tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>"""
    st.markdown(html, unsafe_allow_html=True)


def _inject_live_trade_prices_js() -> None:
    """Injecte un poller JS (iframe invisible) qui met à jour les colonnes
    Progression et la ligne synthèse en temps réel, sans rechargement de page.
    
    Utilise st.components.v1.html() comme les cartes de prix — le JS s'exécute
    dans un iframe srcdoc (même origine) et accède au DOM parent.
    """
    import streamlit.components.v1 as _cv1
    _cv1.html("""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head><body>
<script>
(function() {
  if (window._atlasLiveTradePoller) return;
  window._atlasLiveTradePoller = true;

  function apiUrl() {
    try {
      var p = window.top.location.protocol;
      var h = window.top.location.hostname;
      if (p === 'https:') return p + '//' + h + '/api';
      return 'http://' + h + ':8000';
    } catch(e) {}
    return 'http://192.168.1.80:8000';
  }

  function updateCell(el, price) {
    var entry = parseFloat(el.getAttribute('data-atlas-entry'));
    var size = parseFloat(el.getAttribute('data-atlas-size'));
    var action = el.getAttribute('data-atlas-action');
    if (!entry || !size || !price) return;
    var pnlPct;
    if (action === 'SHORT' || action === 'SELL') {
      pnlPct = (entry - price) / entry * 100;
    } else {
      pnlPct = (price - entry) / entry * 100;
    }
    var unrealized = size * pnlPct / 100;
    var color = unrealized >= 0 ? '#2ecc71' : '#e74c3c';
    el.style.color = color;
    el.style.opacity = '1';
    el.textContent = (unrealized >= 0 ? '+' : '') + unrealized.toFixed(2) + '$ (' + (pnlPct >= 0 ? '+' : '') + pnlPct.toFixed(2) + '%)';
  }

  // Mise à jour du P&L réel carry (basis + funding) via /v7/carry-pnl
  function updateCarryCells(carryData) {
    if (!carryData || !carryData.trades) return;
    var parentDoc = window.top.document;
    var totalRealPnl = 0, totalSize = 0;
    var tradeMap = {};
    carryData.trades.forEach(function(t) {
      tradeMap[t.symbol] = t;
    });
    parentDoc.querySelectorAll('[data-atlas-open="1"]').forEach(function(el) {
      var action = el.getAttribute('data-atlas-action');
      if (action !== 'CARRY') return;
      var sym = el.getAttribute('data-atlas-symbol');
      var t = tradeMap[sym];
      if (!t) return;
      var realPnl = t.real_pnl;
      var realPct = t.real_pnl_pct;
      var size = parseFloat(el.getAttribute('data-atlas-size')) || 0;
      var color = realPnl >= 0 ? '#2ecc71' : '#e74c3c';
      el.style.color = color;
      el.style.opacity = '1';
      el.textContent = (realPnl >= 0 ? '+' : '') + realPnl.toFixed(2) + '$ (' + (realPct >= 0 ? '+' : '') + realPct.toFixed(2) + '%) ⚡';
      totalRealPnl += realPnl;
      totalSize += size;
    });
    // Update summary with real carry P&L
    var sumEl = parentDoc.getElementById('atlas-summary-prog');
    if (sumEl && totalSize > 0) {
      var sumPct = totalRealPnl / totalSize * 100;
      var sumColor = totalRealPnl >= 0 ? '#2ecc71' : '#e74c3c';
      sumEl.style.color = sumColor;
      sumEl.textContent = (totalRealPnl >= 0 ? '+$' : '-$') + Math.abs(totalRealPnl).toFixed(2)
        + ' (' + (sumPct >= 0 ? '+' : '') + sumPct.toFixed(2) + '%) ⚡ carry';
    }
  }

  function updateAll(prices) {
    var totalUnreal = 0, totalSize = 0;
    var parentDoc = window.top.document;
    parentDoc.querySelectorAll('[data-atlas-open="1"]').forEach(function(el) {
      var action = el.getAttribute('data-atlas-action');
      if (action === 'CARRY') return;  // handled by updateCarryCells
      var sym = el.getAttribute('data-atlas-symbol');
      var priceData = prices[sym];
      if (priceData && priceData.price) {
        updateCell(el, priceData.price);
        var entry = parseFloat(el.getAttribute('data-atlas-entry'));
        var size = parseFloat(el.getAttribute('data-atlas-size'));
        if (entry && size) {
          var pct = (action === 'SHORT' || action === 'SELL')
            ? (entry - priceData.price) / entry
            : (priceData.price - entry) / entry;
          totalUnreal += size * pct;
          totalSize += size;
        }
      }
    });
    // Update summary for non-carry trades (carry summary handled by updateCarryCells)
    // Only update if there are non-carry trades with size
    if (totalSize > 0 && !carryDataActive()) {
      var sumEl = parentDoc.getElementById('atlas-summary-prog');
      if (sumEl) {
        var sumPct = totalUnreal / totalSize * 100;
        var sumColor = totalUnreal >= 0 ? '#2ecc71' : '#e74c3c';
        sumEl.style.color = sumColor;
        sumEl.textContent = (totalUnreal >= 0 ? '+$' : '-$') + Math.abs(totalUnreal).toFixed(2)
          + ' (' + (sumPct >= 0 ? '+' : '') + sumPct.toFixed(2) + '%)';
      }
    }
  }

  function carryDataActive() {
    // Check if any carry trades exist
    var parentDoc = window.top.document;
    var els = parentDoc.querySelectorAll('[data-atlas-open="1"][data-atlas-action="CARRY"]');
    return els.length > 0;
  }

  function pollSpot() {
    fetch(apiUrl() + '/prices/snapshot')
      .then(function(r) { return r.json(); })
      .then(function(data) { updateAll(data); })
      .catch(function() {});
  }

  function pollCarry() {
    if (!carryDataActive()) return;
    fetch(apiUrl() + '/v7/carry-pnl')
      .then(function(r) { return r.json(); })
      .then(function(data) { updateCarryCells(data); })
      .catch(function() {});
  }

  setInterval(pollSpot, 3000);
  setInterval(pollCarry, 30000);  // carry P&L évolue lentement (funding 8h, basis) + endpoint ccxt lourd
  pollSpot();
  setTimeout(pollCarry, 1000);
})();
</script>
</body></html>""", height=0)


def _apply_optimized_params(cfg: dict) -> int:
    """Copie les _optimized_* vers les params réels (actifs non verrouillés).

    NOTE: `capital` is NOT copied - the optimiser overwrote it to $500,
    écrasant le capital cible de $2,000/actif. Le safety_cap garde un
    plancher de $100.
    """
    assets = cfg.get("assets", {})
    count = 0
    for sym, p in assets.items():
        if p.get("locked", False):
            continue
        changed = False
        for opt_key, real_key in [("_optimized_stress_loss_pct", "stress_loss_pct"),
                                   ("_optimized_safety_cap", "safety_cap"),
                                   ("_optimized_max_hold_days", "max_hold_days")]:
            # Note: min_funding is NOT applied - too sensitive, the 0.005% default works better
            if opt_key in p:
                val = p[opt_key]
                if real_key == "safety_cap":
                    val = max(100, int(val))
                cfg["assets"][sym][real_key] = val
                changed = True
        if changed:
            count += 1
    if count > 0:
        from v7.core.asset_config import save_config, reload_config
        save_config(cfg)
        reload_config()
    return count


def _reload_api_config():
    """POST /carry/reload-config — applique carry_assets.yaml au process API.

    Le dashboard écrit le fichier, mais l'API en garde une copie en cache :
    without this call, an asset enabled here was only picked up after
    redémarrage du container.
    """
    import urllib.request, json
    try:
        req = urllib.request.Request(f"{_API_BASE}/carry/reload-config", method="POST")
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read())
        n = result.get("n_assets", 0)
        assets = ", ".join(a.split("/")[0] for a in result.get("active_assets", []))
        st.success(t("carry_reload_ok").format(n=n, assets=assets))
        if result.get("errors"):
            st.warning(t("carry_reload_warn").format(errors="; ".join(result["errors"][:3])))
    except Exception as exc:
        st.error(t("carry_reload_error").format(err=exc))


def _carry_logo_md(sym: str, params: dict) -> str:
    """Retourne un logo Markdown pour la barre d'expander (compatible label Streamlit).
    
    Fallback : upload local > SVG git > initiales texte.
    """
    from pathlib import Path as _P
    import base64 as _b64
    ticker = sym.split("/")[0]
    size = 18

    # 1) Uploaded logo
    logo_file = params.get("icon_url", "")
    if logo_file:
        logo_path = _P("/app/data/logos") / logo_file
        if logo_path.exists():
            ext = logo_path.suffix.lower()
            mime = "image/svg+xml" if ext == ".svg" else "image/png"
            data = _b64.b64encode(logo_path.read_bytes()).decode()
            return f"![icon](data:{mime};base64,{data})"

    # 2) Logo git-tracked
    for ext in (".svg", ".png", ".webp", ".jpg"):
        git_path = _P("/app/src/images/assets") / f"{ticker}{ext}"
        if git_path.exists():
            mime = "image/svg+xml" if ext == ".svg" else "image/png"
            data = _b64.b64encode(git_path.read_bytes()).decode()
            return f"![icon](data:{mime};base64,{data})"

    # 3) Fallback texte (initiales entre crochets)
    initial = ticker[:2].upper() if len(ticker) > 1 else ticker[0].upper()
    return f"[{initial}]"


def _render_carry_config():
    """Funding carry asset config editor - reads/writes carry_assets.yaml."""
    st.markdown(f"### {t('tab_carry_cfg')}")
    st.caption(t("carry_cfg_subtitle"))

    # Show a persistent message (so it does not vanish on rerun)
    msg = st.session_state.pop("_carry_msg", None)
    if msg:
        st.success(msg)

    try:
        from v7.core.asset_config import load_config, save_config, get_all_assets, reload_config
    except ImportError:
        st.warning(t("asset_config_module_unavailable"))
        return

    cfg = load_config()
    assets = cfg.get("assets", {})
    global_cfg = cfg.get("global", {})

    # ── Scanner meta info ──
    scanner_meta = cfg.get("_scanner_meta", {})
    if scanner_meta:
        st.caption(t("carry_scan_last").format(
            n=scanner_meta.get('total_eligible', '?'),
            t=scanner_meta.get('total_spot_pairs', '?')))
    else:
        st.caption(t("carry_optimize_prerequisite"))

    # -- 4 buttons on a single row --
    col_b1, col_b2, col_b3, col_b4 = st.columns(4)
    with col_b1:
        if st.button(t("carry_scan_btn"), help=t("carry_scan_help"), use_container_width=True):
            with st.spinner(t("carry_scanning")):
                try:
                    from v7.core.carry_scanner import scan_carry_universe
                    from v7.core.asset_config import reload_config
                    scan_carry_universe(save=True)
                    reload_config()
                    st.session_state["_carry_msg"] = t("carry_scan_ok")
                    st.rerun()
                except Exception as exc:
                    st.error(f"{t('carry_scan_error')} — {exc}")
    with col_b2:
        if st.button(t("carry_optimize_btn"), help=t("carry_optimize_help"), use_container_width=True):
            with st.spinner("Computing the optimised parameters..."):
                try:
                    from v7.core.carry_scanner import scan_carry_universe
                    from v7.core.asset_config import reload_config
                    scan_carry_universe(save=True, optimize=True)
                    reload_config()
                    st.session_state["_carry_msg"] = "📊 Optimised parameters computed (see the _optimized_* fields)"
                    st.rerun()
                except Exception as exc:
                    st.error(f"Optimization failed — {exc}")
    with col_b3:
        if st.button(t("carry_apply_optimized_btn"), type="secondary", use_container_width=True,
                     help=t("carry_apply_optimized_help")):
            count = _apply_optimized_params(cfg)
            st.session_state["_carry_msg"] = f"📊 Optimised parameters applied to {count} assets" if count > 0 else "📊 No change - already optimal"
            st.rerun()
    with col_b4:
        if st.button(t("carry_apply_reload_btn"), type="primary", use_container_width=True,
                     help=t("carry_apply_reload_help")):
            _reload_api_config()

    # ── Warning: actifs non viables ──
    non_viable = [sym for sym, p in assets.items() 
                  if p.get("_optimized_viable") is False and p.get("enabled", True) and not p.get("locked", False)]
    if non_viable:
        st.warning(f"⚠️ {len(non_viable)} non-viable assets detected (backtest: 0 trades, extreme MaxDD, or negative Sharpe)")
        if st.button(t("carry_disable_btn").format(n=len(non_viable)), type="secondary"):
            for sym in non_viable:
                if sym in cfg.get("assets", {}):
                    cfg["assets"][sym]["enabled"] = False
            save_config(cfg)
            reload_config()
            st.session_state["_carry_msg"] = t("carry_disabled_ok").format(n=len(non_viable))
            st.rerun()
    
    # ── Global settings ──
    with st.expander(t("carry_global_params"), expanded=False):
        col1, col2, col3 = st.columns(3)
        with col1:
            new_total = st.number_input(t("carry_total_capital"), value=float(global_cfg.get("total_capital", 14000)), step=1000.0)
        with col2:
            new_max_exp = st.slider(t("carry_max_exposure"), 10, 80, int(global_cfg.get("max_total_exposure_pct", 0.40) * 100)) / 100
        with col3:
            new_max_pos = st.number_input(t("carry_max_positions"), 1, 13, int(global_cfg.get("max_simultaneous_positions", 4)))
        
        col4, col5, col6 = st.columns(3)
        with col4:
            new_rt_cost = st.number_input(t("carry_roundtrip_cost"), 10, 100, int(global_cfg.get("round_trip_cost_bps", 48)))
        with col5:
            new_hold = st.number_input(t("carry_hold_days"), 14, 180, int(global_cfg.get("estimated_hold_days", 60)))
        with col6:
            new_staking = st.number_input(
                t("carry_staking_annual"), 0.0, 20.0,
                float(global_cfg.get("staking_annual", 0.05)) * 100, 0.5,
                format="%.1f", help=t("carry_staking_annual_help"),
            ) / 100

        if st.button(t("carry_save_global_btn"), key="save_global"):
            # Merge rather than replace: a rebuilt dict used to erase the keys
            # not exposed here (staking_annual in particular).
            cfg["global"] = {
                **cfg.get("global", {}),
                "total_capital": new_total,
                "max_total_exposure_pct": new_max_exp,
                "max_simultaneous_positions": int(new_max_pos),
                "round_trip_cost_bps": int(new_rt_cost),
                "estimated_hold_days": int(new_hold),
                "staking_annual": new_staking,
            }
            save_config(cfg)
            st.success(t("carry_save_global_ok"))
            st.rerun()

    st.markdown("---")

    # ── Per-asset table ──
    st.markdown(f"#### {t('carry_configured_assets')}")

    all_symbols = get_all_assets()

    if not all_symbols:
        st.warning(t("carry_no_assets"))
        return

    # Collapse/Expand all (on the right)
    col_spacer, col_exp2, col_exp1 = st.columns([6, 1, 1])
    with col_exp1:
        if st.button(t("carry_expand_all"), key="expand_all"):
            st.session_state["_carry_expand"] = True
            st.rerun()
    with col_exp2:
        if st.button(t("carry_collapse_all"), key="collapse_all"):
            st.session_state["_carry_expand"] = False
            st.rerun()
    expand_default = st.session_state.get("_carry_expand", None)

    for sym in all_symbols:
        params = assets.get(sym, {})
        enabled = params.get("enabled", False)
        icon = "🟢" if enabled else "⚫"
        # Markdown logo for the expander bar (HTML does not work in labels)
        logo_md = _carry_logo_md(sym, params)
        ticker = sym.split("/")[0]
        # Expand si expand_default=True, collapse si False, sinon comportement normal (enabled)
        expanded = expand_default if expand_default is not None else enabled

        with st.expander(f"{icon} {logo_md} {sym}", expanded=expanded):
            col1, col2, col3 = st.columns([1, 1, 1])

            with col1:
                new_enabled = st.checkbox(t("carry_enabled"), value=enabled, key=f"en_{sym}")
                new_locked = st.checkbox(t("carry_locked"), value=params.get("locked", False), key=f"lock_{sym}",
                                         help=t("carry_locked_help"))
                new_capital = st.number_input(t("carry_capital"), value=float(params.get("capital", 2000)), step=500.0, key=f"cap_{sym}")
                new_fraction = st.slider(t("carry_fraction"), 0.10, 1.0, float(params.get("fraction", 0.50)), 0.05, key=f"frac_{sym}")

            with col2:
                new_cap = st.number_input(t("carry_safety_cap"), value=int(params.get("safety_cap", 200)), step=50, key=f"scap_{sym}")
                new_stress = st.slider(t("carry_stress_loss"), 1.0, 20.0, float(params.get("stress_loss_pct", 0.10)) * 100, 1.0, key=f"stress_{sym}") / 100
                new_leverage = st.selectbox(t("carry_leverage"), [1.0, 1.5, 2.0, 3.0], index=[1.0, 1.5, 2.0, 3.0].index(float(params.get("leverage", 1.0))) if float(params.get("leverage", 1.0)) in [1.0, 1.5, 2.0, 3.0] else 0, key=f"lev_{sym}")

            with col3:
                new_min_fund = st.number_input(t("carry_min_funding"), 0.00001, 0.01, float(params.get("min_funding", 0.00005)), format="%.5f", key=f"minf_{sym}")
                new_max_hold = st.number_input(t("carry_max_hold"), 7, 90, int(params.get("max_hold_days", 14)), key=f"mhold_{sym}")
                new_exit_h = st.number_input(t("carry_exit_hours"), 24, 240, int(params.get("exit_after_hours", 72)), step=24, key=f"exit_{sym}")
                # Logo preview (3-level fallback: upload > git SVG > colored circle)
                try:
                    from dashboard.multi_asset import _asset_icon as _get_icon
                    logo_html = _get_icon(sym)
                    st.markdown(f"**{t('carry_logo')}:** {logo_html}", unsafe_allow_html=True)
                except Exception:
                    logo_html = ""
                new_logo_file = st.file_uploader(t("carry_logo"), type=["png","svg","jpg","webp"], key=f"logo_{sym}",
                                                help=t("carry_logo_help"), label_visibility="collapsed")

            # Detect changes (the logo file is handled separately)
            logo_changed = new_logo_file is not None
            if (new_enabled != enabled or new_locked != params.get("locked", False) or
                new_capital != params.get("capital", 2000) or
                new_fraction != params.get("fraction", 0.50) or new_cap != params.get("safety_cap", 200) or
                new_stress != params.get("stress_loss_pct", 0.10) or
                new_leverage != params.get("leverage", 1.0) or
                new_min_fund != params.get("min_funding", 0.00005) or
                new_max_hold != params.get("max_hold_days", 14) or
                new_exit_h != params.get("exit_after_hours", 72) or
                logo_changed):
                if st.button(f"{t('carry_save_asset_btn')} {sym}", key=f"save_{sym}"):
                    # Save the logo
                    logo_filename = params.get("icon_url", "")
                    if logo_changed and new_logo_file is not None:
                        logos_dir = Path("/app/data/logos")
                        logos_dir.mkdir(parents=True, exist_ok=True)
                        ext = new_logo_file.name.rsplit(".", 1)[-1] if "." in new_logo_file.name else "png"
                        logo_filename = f"{sym.replace('/', '_').lower()}.{ext}"
                        with open(logos_dir / logo_filename, "wb") as f:
                            f.write(new_logo_file.getbuffer())
                    
                    cfg["assets"][sym] = {
                        "enabled": new_enabled,
                        "locked": new_locked,
                        "capital": new_capital,
                        "fraction": new_fraction,
                        "safety_cap": int(new_cap),
                        "stress_loss_pct": new_stress,
                        "max_hold_days": int(new_max_hold),
                        "min_funding": new_min_fund,
                        "max_funding": float(params.get("max_funding", 0.003)),
                        "exit_after_hours": int(new_exit_h),
                        "leverage": new_leverage,
                        "icon_url": logo_filename,
                    }
                    save_config(cfg)
                    st.success(t("carry_save_asset_ok").format(sym=sym))
                    st.rerun()

    # -- Summary --
    st.markdown("---")
    active_count = sum(1 for s in all_symbols if assets.get(s, {}).get("enabled", False))
    st.metric(t("carry_active_count"), f"{active_count}/{len(all_symbols)}")
    st.caption(t("carry_dag_hint"))


def _render_backtest_v4():
    """Backtest panel — funding carry (short perp + long spot, market-neutral)."""
    st.markdown("### 🧪 Backtest")
    # ── Funding Carry Backtest ──
    st.caption(t("backtest_carry_caption"))
    
    # Load the assets from carry_assets.yaml
    get_asset_params = None
    try:
        from v7.core.asset_config import get_active_assets, get_asset_params
        _bt_assets = get_active_assets()
        if not _bt_assets:
            _bt_assets = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT"]
    except Exception:
        _bt_assets = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT"]
    
    # Scope selector - ALL (every active asset) or a single asset.
    # The script accepts ACTIVE (enabled assets) / ALL (every declared asset).
    _SCOPE_ACTIVE, _SCOPE_ALL = "__ACTIVE__", "__ALL__"
    _opt_labels = [t("backtest_scope_active"), t("backtest_scope_all")] + list(_bt_assets)
    _opt_values = {t("backtest_scope_active"): _SCOPE_ACTIVE,
                   t("backtest_scope_all"): _SCOPE_ALL}
    for _s in _bt_assets:
        _opt_values[_s] = _s
    _choice_label = st.selectbox(t("col_asset"), _opt_labels)
    symbol = _opt_values[_choice_label]
    _is_group = symbol in (_SCOPE_ACTIVE, _SCOPE_ALL)

    _n_scope = len(_bt_assets)
    if _is_group:
        try:
            from v7.core.asset_config import get_all_assets
            _n_scope = len(_bt_assets) if symbol == _SCOPE_ACTIVE else len(get_all_assets())
        except Exception:
            _n_scope = len(_bt_assets)
        st.caption(t("backtest_scope_caption").format(n=_n_scope))

    days = st.slider(t("backtest_days_history"), 30, 1095, 365, 30)
    
    # Defaults come from carry_assets.yaml (single source), no hardcoded constants
    _btp: dict = {}
    try:
        if get_asset_params and not _is_group:
            _btp = get_asset_params(symbol) or {}
    except Exception:
        _btp = {}

    capital, fraction = 2000.0, 0.50
    if _is_group:
        # Group runs let the script read each asset's own settings from the config
        st.info(t("backtest_per_asset_note"))
    else:
        col1, col2 = st.columns(2)
        with col1:
            capital = st.number_input(t("backtest_capital"), 100, 100000,
                                      int(_btp.get("capital", 2000)), 100,
                                      help=t("backtest_capital_help"))
        with col2:
            fraction = st.slider(t("backtest_fraction"), 0.10, 1.0,
                                 float(_btp.get("fraction", 0.50)), 0.05,
                                 help=t("backtest_fraction_help"))
    
    if st.button(t("backtest_run_btn"), type="primary", use_container_width=True):
        _cli_symbol = ("ACTIVE" if symbol == _SCOPE_ACTIVE
                       else "ALL" if symbol == _SCOPE_ALL else symbol)
        _cmd = [sys.executable, "v7/backtest_v7_node.py",
                "--symbol", _cli_symbol, "--days", str(days)]
        # Single-asset runs honour the on-screen overrides; group runs let the
        # script read each asset's own capital/fraction from the config.
        if not _is_group:
            _cmd += ["--capital", str(int(capital)),
                     "--fraction", str(round(fraction, 4))]
        # Detached run: a 77-asset sweep takes ~5 minutes, which is far too long
        # to block the Streamlit script (the connection would be dropped and the
        # whole page would appear to hang). We spawn it, write to a log file and
        # poll that file instead.
        for _f in (_BT_LOG, _BT_RC):
            try:
                os.remove(_f)
            except OSError:
                pass
        _shell = shlex.join(_cmd) + f"; echo $? > {_BT_RC}"
        with open(_BT_LOG, "w") as _fh:
            _fh.write(f"$ {shlex.join(_cmd)}\n\n")
        _fh_out = open(_BT_LOG, "a")
        subprocess.Popen(["/bin/sh", "-c", _shell], stdout=_fh_out,
                         stderr=subprocess.STDOUT, cwd="/app/src",
                         start_new_session=True)
        _fh_out.close()
        st.session_state["_bt_started"] = time.time()
        st.rerun()

    # ── Follow the run started from this page (survives a reload) ──
    _bt_state = _backtest_run_state()
    if _bt_state != "idle":
        _elapsed = time.time() - st.session_state.get("_bt_started", time.time())
        try:
            _log_txt = open(_BT_LOG, encoding="utf-8", errors="replace").read()
        except OSError:
            _log_txt = ""
        if _bt_state == "running":
            st.info(t("backtest_bg_running").format(elapsed=int(_elapsed)))
            _done = sum(1 for _l in _log_txt.split("\n") if _l.startswith("  ")
                        and "Trade=$" in _l)
            if _done:
                st.caption(t("backtest_bg_progress").format(done=_done, total=_n_scope))
            st.code(_log_txt[-4000:] if len(_log_txt) > 4000 else _log_txt)
            time.sleep(3)
            st.rerun()
        else:
            _rc = _backtest_exit_code()
            if _rc == 0:
                st.success(t("backtest_bg_done").format(elapsed=int(_elapsed)))
            else:
                st.error(t("backtest_bg_error").format(rc=_rc))
            st.code(_log_txt[-12000:] if len(_log_txt) > 12000 else _log_txt)
            for _line in _log_txt.split("\n"):
                if any(kw in _line for kw in ("TRADING (the strategy)", "NO TRADE", "Mean Sharpe")):
                    st.text(_line.strip())

_LOGS_PAGE_SIZE = 100


def render_live_logs(key: str = "global", asset: str | None = None):
    """Show the carry cycle logs (100 rows per page)."""
    col_title, col_del = st.columns([5, 1])
    with col_title:
        st.markdown(
            f'<h3 style="margin:0 0 12px;font-size:18px;">'
            f'<i class="fas fa-terminal" style="margin-right:8px;color:#7986cb;"></i>'
            f'{t("logs_title")}</h3>',
            unsafe_allow_html=True,
        )

    # ── Logs V4 (API) ───────────────────────────────────────────────────
    v4_logs: list[dict] = []
    try:
        import urllib.request, json as _json
        req = urllib.request.Request(f"{_API_BASE}/dag/logs?n=50", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            v4_logs = _json.loads(resp.read())
    except Exception:
        pass

    if v4_logs:
        st.markdown(
            '<p style="margin:0 0 6px;font-size:12px;font-weight:600;color:#4f6ef7;">'
            '📊 Atlas — Cycle Carry Live</p>',
            unsafe_allow_html=True,
        )
        theme = _get_theme()
        log_bg = "#161b22" if theme == "dark" else "#f8f9fa"
        log_border = "rgba(255,255,255,0.08)" if theme == "dark" else "#dee2e6"
        for entry in v4_logs[-30:]:
            ts = entry.get("ts", "")
            level = entry.get("level", "INFO")
            msg = entry.get("message", "")
            lvl_color = {"ERROR": "#ef4444", "WARN": "#f59e0b", "INFO": "#22c55e", "DEBUG": "#888"}.get(level, "#888")
            st.markdown(
                f'<div style="font-family:monospace;font-size:11px;padding:2px 8px;'
                f'background:{log_bg};border-left:3px solid {lvl_color};margin:1px 0;">'
                f'<span style="color:#888;">{ts[-8:] if ts else "--"}</span> '
                f'<span style="color:{lvl_color};">{level}</span> '
                f'<span>{msg}</span></div>',
                unsafe_allow_html=True,
            )
        st.markdown('<div style="margin-bottom:12px;"></div>', unsafe_allow_html=True)
    with col_del:
        if st.button(t("clear_btn"), key=f"btn_clear_logs_{key}",
                     help=t("clear_btn_help"),
                     use_container_width=True):
            st.info(t("logs_memory_caption"), icon="ℹ️")
    # DB-backed logs - only when the V4 logs are empty (no duplication)
    if not v4_logs:
        try:
            from storage.database import get_connection
            with get_connection() as conn:
                if asset:
                    _slug = asset.replace("/", "")
                    _pat1, _pat2 = f"%{asset}%", f"%{_slug}%"
                    # V7: dag_logs first, logs as fallback
                    total_rows = conn.execute(
                        "SELECT COUNT(*) FROM dag_logs WHERE message LIKE ? OR message LIKE ?",
                        (_pat1, _pat2),
                    ).fetchone()[0]
                    if total_rows == 0:
                        total_rows = conn.execute(
                            "SELECT COUNT(*) FROM logs WHERE message LIKE ? OR message LIKE ?",
                            (_pat1, _pat2),
                        ).fetchone()[0]
                        all_rows = conn.execute(
                            "SELECT timestamp, level, module, message FROM logs "
                            "WHERE message LIKE ? OR message LIKE ? "
                            "ORDER BY timestamp DESC",
                            (_pat1, _pat2),
                        ).fetchall()
                    else:
                        all_rows = conn.execute(
                            "SELECT ts, level, dag_id, message FROM dag_logs "
                            "WHERE message LIKE ? OR message LIKE ? "
                            "ORDER BY ts DESC",
                            (_pat1, _pat2),
                        ).fetchall()
                else:
                    total_rows = conn.execute("SELECT COUNT(*) FROM dag_logs").fetchone()[0]
                    if total_rows == 0:
                        total_rows = conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
                        all_rows = conn.execute(
                            "SELECT timestamp, level, module, message FROM logs "
                            "ORDER BY timestamp DESC"
                        ).fetchall()
                    else:
                        all_rows = conn.execute(
                            "SELECT ts, level, dag_id, message FROM dag_logs "
                            "ORDER BY ts DESC"
                        ).fetchall()
        except Exception:
            st.info(t("logs_unavailable"))
            return

        if not all_rows:
            st.info(t("no_logs"))
            return

        total_pages = max(1, (total_rows + _LOGS_PAGE_SIZE - 1) // _LOGS_PAGE_SIZE)

        # ── Barre de navigation ──────────────────────────────────────────────────
        col_info, col_nav = st.columns([3, 2])
        with col_info:
            st.caption(t("logs_lines_pages").format(n=total_rows, p=total_pages, ps="s" if total_pages > 1 else ""))
        with col_nav:
            page = st.number_input(
                "Page", min_value=1, max_value=total_pages,
                value=1, step=1, key=f"logs_page_{key}",
                label_visibility="collapsed",
            )

        # ── Tranche de la page courante ──────────────────────────────────────────
        start = (page - 1) * _LOGS_PAGE_SIZE
        page_rows = all_rows[start : start + _LOGS_PAGE_SIZE]

        log_lines = []
        for row in page_rows:
            level_color = {
                "DEBUG": "#6c757d", "INFO": "#0dcaf0",
                "WARNING": "#ffc107", "ERROR": "#dc3545",
            }.get(row[1], "#fff")
            try:
                _ts = _fmt_utc_local(datetime.fromisoformat(str(row[0])))
            except Exception:
                _ts = html.escape(str(row[0]))
            _mod = html.escape(str(row[2]))
            _msg = html.escape(str(row[3]))
            log_lines.append(
                f'<span style="color:#6c757d">{_ts}</span> '
                f'<span style="color:{level_color}">[{row[1]}]</span> '
                f'<span style="color:#adb5bd">[{_mod}]</span> {_msg}'
            )

        st.markdown(
            f'<div style="border:1px solid rgba(128,128,128,0.2);padding:12px;border-radius:8px;'
            f'font-family:monospace;font-size:11px;max-height:400px;'
            f'overflow-y:auto;">{"<br>".join(log_lines)}</div>',
            unsafe_allow_html=True,
        )


# ===========================================================
# INTERFACE ADMIN
# ===========================================================

## render_admin_login() replaced by dashboard.auth.render_auth(cm)


def render_admin_panel():
    """Full admin panel - monitoring and configuration of the carry strategy."""
    # Guard: no auth UI may render while the admin view is displayed.
    st.session_state["_suppress_auth_ui"] = True
    st.session_state.pop("_auth_step", None)
    st.session_state.pop("_auth_pending_user", None)
    st.session_state.pop("_auth_totp_new_secret", None)

    # ── Navigation admin via sidebar custom ───────────────────────────────────────
    from dashboard.multi_asset import _inject_custom_sidenav

    _ADMIN_SECTIONS = [
        # ── Carry Engine ──────────────────────────────────────────
        (None, None,      "Carry V7"),
        ('<i class="fas fa-chart-line"></i>',      "v4_monitor", "Live Monitor"),
        ('<i class="fas fa-receipt"></i>',         "v4_trades",  "Trades"),
        ('<i class="fas fa-coins"></i>',            "carry_cfg",  "Carry Assets"),
        # ── Journal ───────────────────────────────────────────────
        (None, None,      "Journal"),
        ('<i class="fas fa-history"></i>',         "historique", "History"),
        ('<i class="fas fa-brain"></i>',           "decisions",   "Decisions"),
        ('<i class="fas fa-flask"></i>',           "backtest",   "Backtest"),
        # -- System --
        (None, None,      "System"),
        ('<i class="fas fa-user"></i>',            "users",      "Users"),
        ('<i class="fas fa-floppy-disk"></i>',     "backup",     "Backup"),
        ('<i class="fas fa-trash-alt"></i>',       "reset",      "Reset"),
    ]
    _admin_keys = [s[1] for s in _ADMIN_SECTIONS if s[1] is not None]
    _admin_items = [
        {"section": s[2]} if s[1] is None
        else {"key": s[1], "icon": s[0], "text": s[2]}
        for s in _ADMIN_SECTIONS
    ]
    _atab = st.query_params.get("_atab", "v4_monitor")
    if _atab not in _admin_keys:
        _atab = "v4_monitor"
    _inject_custom_sidenav(_admin_items, _atab, qparam="_atab", theme=_get_theme())

    if _atab == "users":  # Utilisateurs
        st.markdown('<h4><i class="fas fa-user" style="margin-right:7px;color:#7986cb;"></i> Utilisateurs</h4>', unsafe_allow_html=True)
        st.info(t("cfg_users_info"))
        from dashboard.auth import render_users_admin
        render_users_admin()
        # backup handled in render_users_admin

    elif _atab == "backup":  # Sauvegarde / Restauration
        st.markdown(f'<h4><i class="fas fa-floppy-disk" style="margin-right:7px;color:#7986cb;"></i>{t("bkp_title")}</h4>', unsafe_allow_html=True)
        st.info(t("bkp_info"))

        col_exp, col_imp = st.columns(2)

        with col_exp:
            st.subheader(t("bkp_export_title"))
            st.caption(t("bkp_export_caption"))
            try:
                from utils.config import export_config_zip
                from datetime import datetime as _dt
                _zip_bytes = export_config_zip()
                _zip_name  = f"atlas_config_{_dt.utcnow().strftime('%Y%m%d_%H%M%S')}.zip"
                st.download_button(
                    label=t("bkp_download_btn"),
                    data=_zip_bytes,
                    file_name=_zip_name,
                    mime="application/zip",
                    use_container_width=True,
                )
                st.success(t("bkp_ready").format(n=len(_zip_bytes)//1024))
            except Exception as _exp_exc:
                st.error(f"{t('bkp_export_error')} {_exp_exc}")

        with col_imp:
            st.subheader(t("bkp_import_title"))
            st.caption(t("bkp_import_caption"))
            _up = st.file_uploader(t("bkp_choose_file"), type=["zip"], label_visibility="collapsed")
            _confirm = st.checkbox(t("bkp_confirm_check"))
            if st.button(t("bkp_restore_btn"), disabled=(_up is None or not _confirm), use_container_width=True):
                try:
                    from utils.config import import_config_zip
                    _result = import_config_zip(_up.read(), backup_first=True)
                    st.success(
                        t("bkp_restore_success").format(n=len(_result['restored_files']))
                        + (f"\n{t('bkp_backup_path')} `{_result['backup_path']}`" if _result['backup_path'] else "")
                    )
                    if _result["errors"]:
                        for _e in _result["errors"]:
                            st.warning(f"⚠️ {_e}")
                    st.info(t("bkp_restart_info"))
                except Exception as _imp_exc:
                    st.error(f"{t('bkp_restore_error')} {_imp_exc}")

        # Liste des sauvegardes automatiques disponibles
        st.markdown("---")
        st.subheader(t("bkp_list_title"))
        try:
            from utils.config import list_config_backups, import_config_zip
            _backups = list_config_backups()
            if not _backups:
                st.caption(t("bkp_no_backups"))
            else:
                for _bk in _backups[:10]:  # at most 10 shown
                    _bcol1, _bcol2, _bcol3 = st.columns([4, 1, 1])
                    with _bcol1:
                        st.caption(f"🗂 `{_bk['filename']}` — {_bk['mtime'].strftime('%d/%m/%Y %H:%M')} UTC — {_bk['size_kb']} Ko")
                    with _bcol2:
                        _bk_bytes = _bk["path"].read_bytes()
                        st.download_button(
                            "⬇️",
                            data=_bk_bytes,
                            file_name=_bk["filename"],
                            mime="application/zip",
                            key=f"dl_{_bk['filename']}",
                        )
                    with _bcol3:
                        if st.button("🔄", key=f"restore_{_bk['filename']}", help="Restore this backup"):
                            try:
                                _r = import_config_zip(_bk_bytes, backup_first=True)
                                st.success(t("bkp_restore_from").format(n=len(_r['restored_files']), filename=_bk['filename']))
                            except Exception as _re:
                                st.error(f"❌ {_re}")
        except Exception as _lb_exc:
            st.caption(f"{t('bkp_list_error')} {_lb_exc}")

    elif _atab == "backtest":  # Backtest
        _render_backtest_v4()

    elif _atab == "reset":  # data purge
        st.markdown(
            f'<h4><i class="fas fa-trash-alt" style="margin-right:7px;color:#e74c3c;"></i>'
            f' Reset Paper Trading</h4>',
            unsafe_allow_html=True,
        )
        st.warning(t("reset_warning_trades"))

        st.markdown(f"#### 🗑️ Reset All Data")
        st.caption(t("reset_caption_trades"))

        confirm = st.checkbox(
            "I understand — delete all trade history",
            key="reset_v4_confirm",
        )
        if st.button(
            "🗑️ Reset Everything",
            type="primary",
            use_container_width=True,
            disabled=not confirm,
        ):
            # 1) Effacer l'historique des trades
            try:
                from storage.database import get_connection
                from storage.paper_trader import _ensure_table
                with get_connection() as conn:
                    _ensure_table(conn)
                    conn.execute("DELETE FROM v4_trades")
                    conn.commit()
                st.success("✅ Trade history deleted.")
            except Exception as e:
                st.error(f"DB error: {e}")

            # 2) Clear the DAG logs (carry cycle logs)
            try:
                from storage.database import get_connection
                with get_connection() as conn:
                    conn.execute("DELETE FROM dag_logs")
                    conn.commit()
                st.success("✅ Cycle logs cleared.")
            except Exception:
                pass

            # 3) Clear the Streamlit cache
            st.cache_data.clear()
            st.success("✅ Dashboard cache cleared. New data will appear on next cycle.")
            time.sleep(1)
            st.rerun()

    elif _atab == "historique":  # Transaction history
        st.markdown(
            f'<h4><i class="fas fa-history" style="margin-right:7px;color:#9c27b0;"></i>'
            f'{t("history_title")}</h4>',
            unsafe_allow_html=True,
        )
        try:
            from storage.paper_trader import get_v4_trades
            from storage.database import get_connection as _hget_conn

            # Filtres
            _h_col1, _h_col2, _h_col3 = st.columns([2, 1, 1])
            with _h_col1:
                _h_asset = st.selectbox(
                    t("col_asset"), [None] + _carry_asset_list(),
                    format_func=lambda v: t("filter_all") if v is None else v,
                    key="hist_asset",
                )
            with _h_col2:
                _h_action = st.selectbox(
                    t("filter_action"), [None, "carry", "long", "short"],
                    format_func=lambda v: t("filter_all") if v is None else v,
                    key="hist_action",
                )
            with _h_col3:
                _h_status = st.selectbox(
                    t("filter_status"), [None, "open", "closed"],
                    format_func=lambda v: t("filter_all") if v is None else v,
                    key="hist_status",
                )

            # Fetch the trades
            all_trades = get_v4_trades(n=2000)
            if not all_trades:
                st.info(t("no_transactions"))
                return

            # Filtrer
            filtered = all_trades
            if _h_asset is not None:
                filtered = [tr for tr in filtered if tr.get("symbol") == _h_asset]
            if _h_action is not None:
                filtered = [tr for tr in filtered if tr.get("action") == _h_action]
            if _h_status is not None:
                filtered = [tr for tr in filtered if tr.get("status") == _h_status]

            if not filtered:
                st.info(t("no_trades"))
                return

            # Stats
            n_total = len(filtered)
            n_open = sum(1 for tr in filtered if tr.get("status") == "open")
            n_closed = sum(1 for tr in filtered if tr.get("status") == "closed")
            total_pnl = sum(float(tr.get("pnl_usd", 0) or 0) for tr in filtered if tr.get("status") == "closed")
            wins = sum(1 for tr in filtered if tr.get("status") == "closed" and float(tr.get("pnl_usd", 0) or 0) > 0)
            losses = sum(1 for tr in filtered if tr.get("status") == "closed" and float(tr.get("pnl_usd", 0) or 0) < 0)
            win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0

            _hc1, _hc2, _hc3, _hc4, _hc5, _hc6 = st.columns(6)
            _hc1.metric("Total", n_total)
            _hc2.metric("Ouverts", n_open)
            _hc3.metric("Closed", n_closed)
            _hc4.metric("P&L total", f"${total_pnl:+,.2f}")
            _hc5.metric("Won", wins)
            _hc6.metric("Win rate", f"{win_rate:.0f}%")

            # Fetch the current prices for the unrealised P&L
            live_prices: dict[str, float] = {}
            try:
                import urllib.request, json as _j
                req = urllib.request.Request(f"{_API_BASE}/prices/snapshot")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    prices_data = _j.loads(resp.read())
                for sym, data in prices_data.items():
                    if isinstance(data, dict):
                        live_prices[sym] = float(data.get("price", 0))
            except Exception:
                pass

            st.markdown("---")

            # Tableau
            # HTML table (theme-aware, no white background)
            theme = _get_theme()
            if theme == "light":
                tbl_bg, tbl_fg, head_bg, border = "#ffffff", "#212529", "#f1f3f5", "#dee2e6"
                row_alt, sep = "#f8f9fa", "#e9ecef"
            else:
                tbl_bg, tbl_fg, head_bg, border = "#161b22", "#e6edf3", "#0d1117", "rgba(255,255,255,0.08)"
                row_alt, sep = "#1b2129", "rgba(255,255,255,0.05)"

            cols = [t("col_date"), t("col_asset"), t("col_action"), t("col_entry"), t("col_size_usd"), t("col_sl"), t("col_tp"), t("col_pnl"), t("col_progression"), t("col_status"), t("col_dag")]
            header = "".join(
                f'<th style="padding:6px 10px;font-size:11px;font-weight:600;'
                f'text-transform:uppercase;letter-spacing:.05em;color:{tbl_fg};opacity:.65;'
                f'background:{head_bg};white-space:nowrap;border-bottom:2px solid {border};">{c}</th>'
                for c in cols
            )
            rows_html = ""
            for i, tr in enumerate(filtered):
                bg = row_alt if i % 2 else tbl_bg
                pnl = float(tr.get("pnl_usd", 0) or 0)
                pnl_str = f"${pnl:+,.2f}" if tr.get("status") == "closed" else "⏳"
                pnl_color = "#2ecc71" if pnl > 0 else ("#e74c3c" if pnl < 0 else tbl_fg)
                action = (tr.get("action") or "").upper()
                action_color = "#2ecc71" if action == "LONG" else ("#e74c3c" if action == "SHORT" else tbl_fg)
                
                # Progression (unrealised P&L for open trades)
                progress_str = "—"
                entry_price = float(tr.get("entry_price", 0) or 0)
                size_usd = float(tr.get("size_usd", 0) or 0)
                current_price = live_prices.get(tr.get("symbol", ""), 0)
                _tid4 = tr.get("trade_id", f"vh{i}")
                _sym4 = tr.get("symbol", "")
                if tr.get("status") == "open" and entry_price > 0 and current_price > 0 and size_usd > 0:
                    if action in ("CARRY", "SHORT"):
                        pnl_pct = (entry_price - current_price) / entry_price * 100
                    else:
                        pnl_pct = (current_price - entry_price) / entry_price * 100
                    unrealized = size_usd * pnl_pct / 100
                    prog_color = "#2ecc71" if unrealized >= 0 else "#e74c3c"
                    progress_str = f'<span id="aprog-{_tid4}" data-atlas-symbol="{_sym4}" data-atlas-entry="{entry_price}" data-atlas-size="{size_usd}" data-atlas-action="{action}" data-atlas-open="1" style="color:{prog_color};">{unrealized:+,.2f}$ ({pnl_pct:+.2f}%)</span>'
                elif tr.get("status") == "open":
                    progress_str = f'<span id="aprog-{_tid4}" data-atlas-symbol="{_sym4}" data-atlas-entry="{entry_price}" data-atlas-size="{size_usd}" data-atlas-action="{action}" data-atlas-open="1" style="opacity:.45;">—</span>'
                
                cells = [
                    (tr.get("timestamp") or "")[:19].replace("T", " "),
                    tr.get("symbol", "—"),
                    f'<span style="color:{action_color};font-weight:600;">{action}</span>',
                    f'${entry_price:,.2f}' if entry_price else "—",
                    f'${float(tr.get("stop_loss", 0)):,.2f}' if tr.get("stop_loss") else "—",
                    f'${float(tr.get("take_profit", 0)):,.2f}' if tr.get("take_profit") else "—",
                    f'${size_usd:,.0f}' if size_usd else "—",
                    f'<span style="color:{pnl_color};font-weight:600;">{pnl_str}</span>',
                    progress_str,
                    f"✅ {t('closed_status')}" if tr.get("status") == "closed" else f"⏳ {t('open_status')}",
                    tr.get("dag_id", "—"),
                ]
                td_style = f'padding:5px 10px;font-size:12px;color:{tbl_fg};white-space:nowrap;border-bottom:1px solid {sep};'
                tds = "".join(f'<td style="{td_style}">{c}</td>' for c in cells)
                rows_html += f'<tr style="background:{bg};">{tds}</tr>'

            st.markdown(
                f'<div style="overflow:auto;max-height:600px;border:1px solid {border};'
                f'border-radius:10px;background:{tbl_bg};margin-bottom:24px;">'
                f'<table style="border-collapse:collapse;width:100%;min-width:900px;">'
                f'<thead><tr>{header}</tr></thead>'
                f'<tbody>{rows_html}</tbody></table></div>',
                unsafe_allow_html=True,
            )

            # Export CSV
            import pandas as _hpd
            _h_df = _hpd.DataFrame(filtered)
            _h_csv = _h_df.to_csv(index=False).encode("utf-8")
            st.download_button(t("export_csv_btn"), _h_csv, file_name="v4_trades.csv", mime="text/csv", key="hist_v4_csv")

            # -- Manual close-all button --
            st.markdown("---")
            st.markdown(f"#### ⚠️ {t('emergency_close_title')}")
            st.caption(t("emergency_close_caption"))
            _n_open_hist = sum(1 for tr in filtered if tr.get("status") == "open")
            if _n_open_hist > 0:
                if st.button(f"🔴 {t('emergency_close_btn')} {_n_open_hist} position(s) ouverte(s)", type="secondary", use_container_width=True):
                    try:
                        import urllib.request as _ur_close, json as _j_close
                        _resp = _ur_close.urlopen(_ur_close.Request(
                            f"{_API_BASE}/dag/close-all", method="POST"), timeout=30)
                        _result = _j_close.loads(_resp.read())
                        st.success(f"✅ {_result['closed']} position(s) closed, {_result['failed']} failed")
                        if _result.get("details"):
                            for d in _result["details"]:
                                st.caption(f"• {d['symbol']} @ ${d['close_price']:,.2f} → P&L ${d['pnl']:+,.2f}")
                        st.rerun()
                    except Exception as _ce:
                        st.error(f"API error: {_ce}")
            else:
                st.info(t("no_open_positions"))

            # Reflections (lessons learned)
            try:
                with _hget_conn() as _hconn:
                    _hconn.execute("""
                        CREATE TABLE IF NOT EXISTS v4_reflections (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            trade_id TEXT UNIQUE, symbol TEXT, action TEXT,
                            entry_price REAL, close_price REAL,
                            pnl_usd REAL, pnl_pct REAL, lesson TEXT, created_at TEXT
                        )
                    """)
                    _ref_rows = _hconn.execute(
                        "SELECT symbol, action, pnl_usd, lesson, created_at FROM v4_reflections ORDER BY created_at DESC LIMIT 50"
                    ).fetchall()
                if _ref_rows:
                    st.markdown("---")
                    st.markdown("#### 🧠 Lessons learned (ReflectionNode)")
                    for r in _ref_rows:
                        emoji = "✅" if (r[2] or 0) > 0 else "❌"
                        st.caption(f"{emoji} {r[0]} {r[1]}: {r[3]} (${r[2]:+.2f})")
            except Exception:
                pass

        except Exception as _he:
            st.error(f"Error reading the V4 history: {_he}")

    elif _atab == "decisions":  # AI decision history
        st.markdown(
            '<h4><i class="fas fa-brain" style="margin-right:7px;color:#9c27b0;"></i>'
            ' Decision History</h4>',
            unsafe_allow_html=True,
        )
        st.caption(t("decisions_caption_cycle"))

        _dcol1, _dcol2 = st.columns([1, 1])
        with _dcol1:
            _dsymbol = st.selectbox(
                t("col_asset"), [None] + _carry_asset_list(),
                format_func=lambda v: t("filter_all") if v is None else v,
                key="dec_symbol",
            )
        with _dcol2:
            _dlimit = st.slider(t("col_number"), 10, 500, 50, 10, key="dec_limit")

        try:
            _dparams = {"n": _dlimit}
            if _dsymbol is not None:
                _dparams["symbol"] = _dsymbol
            import urllib.parse as _uparse
            _durl = f"{_API_BASE}/dag/decisions?" + _uparse.urlencode(_dparams)
            import urllib.request as _urdec, json as _jdec
            _dresp = _jdec.loads(_urdec.urlopen(_durl, timeout=10).read())

            if _dresp.get("error"):
                st.warning(_dresp["error"])
            elif not _dresp.get("decisions"):
                st.info(t("decisions_empty"))
            else:
                decisions = _dresp["decisions"]
                st.markdown(f"**{t('decisions_count').format(n=len(decisions))}**")

                for d in decisions:
                    data = d.get("data", {})
                    signal = data.get("signal") or data.get("action") or "?"
                    reason = data.get("reason", "")[:200]
                    ts = d.get("ts_iso", "")[:19]
                    sym = d.get("symbol", "?")
                    dag = d.get("dag_id", "?")
                    trade_link = d.get("trade_id", "")

                    # Couleur selon signal
                    sig_color = "#2ecc71" if signal in ("open_carry", "carry", "long") else (
                        "#e74c3c" if signal in ("close_carry", "short") else "#ffb74d")
                    
                    with st.expander(
                        f"{ts} — {sym} — {signal} — {reason[:80]}{'...' if len(reason) > 80 else ''}"
                    ):
                        c1, c2 = st.columns([3, 1])
                        with c1:
                            st.json(data)
                        with c2:
                            st.metric("Signal", signal)
                            st.caption(f"DAG: `{dag}`")
                            if trade_link:
                                st.caption(f"Trade: `{trade_link}`")
                            st.caption(f"TS: {ts}")
        except Exception as _de:
            st.error(f"Error loading the decisions: {_de}")

    # Self-contained tabs - each one handles its own rendering and persistence
    if _atab == "carry_cfg":
        _render_carry_config()
        return
    if _atab in ("v4_monitor", "v4_trades"):
        if _atab == "v4_trades":
            st.markdown("### 📋 " + t("trades_journal_title"))
            st.caption(t("paper_trading_mode"))
            _tr = _get_recent_trades(200)
            if _tr:
                render_trades_list_sortable(_tr)
            else:
                st.info(t("no_trades_recorded"))
            return
        if _atab == "v4_monitor":
            st.markdown("### 📊 Live Monitor — Funding Carry V7")
            
            # ── Cycle status ──
            col1, col2, col3 = st.columns(3)
            last_cycle = _get_last_cycle()
            if last_cycle:
                with col1:
                    st.metric("Last Cycle", last_cycle.get("timestamp", "—")[:19])
                with col2:
                    st.metric("Next Cycle", "~8h (auto)")
                with col3:
                    st.metric("Status", "✅ Running" if True else "⏸️")
            
            # ── Open carry positions ──
            st.markdown("#### 🟢 Open Carry Positions")
            try:
                from storage.paper_trader import get_open_positions
                open_pos = get_open_positions()
                carry_pos = [p for p in open_pos if p.get("action") in ("carry", "short")]
                if carry_pos:
                    rows = []
                    for p in carry_pos:
                        # context_json may be a JSON string or a dict
                        ctx = p.get("context_json", {})
                        if isinstance(ctx, str):
                            try:
                                import json as _j
                                ctx = _j.loads(ctx) if ctx else {}
                            except Exception:
                                ctx = {}
                        total_funding = float(ctx.get("total_funding", 0) or 0) if isinstance(ctx, dict) else 0
                        rows.append({
                            "Asset": p.get("symbol", "?"),
                            "Size": f"${float(p.get('size_usd', 0)):,.0f}",
                            "Entry": f"${float(p.get('entry_price', 0)):,.2f}",
                            "Opened": str(p.get("timestamp", "—"))[:19],
                            "Funding Total": f"${total_funding:.4f}",
                        })
                    st.dataframe(rows, use_container_width=True, hide_index=True)
                else:
                    st.info(t("no_open_carry_positions"))
            except Exception as e:
                st.warning(f"Position fetch: {e}")
            
            # ── Recent decisions ──
            st.markdown("#### 🧠 Recent Decisions")
            try:
                decisions = _get_recent_decisions(10)
                if decisions:
                    for d in decisions:
                        action = d.get("action", "?")
                        sym = d.get("symbol", "?")
                        ts = str(d.get("timestamp", "—"))[:19]
                        reason = d.get("reason", d.get("context_json", ""))
                        if isinstance(reason, dict):
                            reason = reason.get("reason", "")
                        emoji = {"carry": "🟢", "close_carry": "🔴", "flat": "➖"}.get(action, "❓")
                        st.caption(f"{emoji} **{sym}** — {action} — {ts}")
                        if reason:
                            st.caption(f"&nbsp;&nbsp;&nbsp;&nbsp;↳ {str(reason)[:120]}")
                else:
                    st.info(t("no_decisions_yet"))
            except Exception as e:
                st.warning(f"Decisions fetch: {e}")
            
            # ── Quick portfolio summary ──
            st.markdown("#### 💼 Portfolio Snapshot")
            _pf = _get_portfolio()
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Capital", f"${_pf.get('capital', 0):,}")
            c2.metric("Exposure", f"${_pf.get('exposure', 0):,.0f}")
            c3.metric("Open Trades", _pf.get("n_trades", 0))
            c4.metric("Total P&L", f"${_pf.get('total_pnl', 0):,.2f}")
            return


# ===========================================================
# SESSION PERSISTENCE (localStorage)
# ===========================================================

def _inject_session_persistence_js(has_valid_session: bool) -> None:
    """
    Persiste _sid dans localStorage pour survivre aux rechargements sans cookie.
    - _sid présent + session valide  → sauvegarde localStorage
    - _sid présent + session invalide → efface localStorage (logout / expiration)
    - _sid absent + localStorage contient un sid → redirige avec _sid dans l'URL
    """
    import streamlit.components.v1 as _cv1
    valid_js = "true" if has_valid_session else "false"
    _cv1.html(
        f"""<script>
(function(){{
  try {{
    var p   = window.parent || window;
    var url = new URL(p.location.href);
    var sid = url.searchParams.get('_sid');
    var ok  = {valid_js};
    if (sid) {{
      if (ok) {{ localStorage.setItem('atlas_sid', sid); }}
      else    {{ localStorage.removeItem('atlas_sid'); }}
    }} else {{
      var s = localStorage.getItem('atlas_sid');
      if (s && s.length > 30) {{
        url.searchParams.set('_sid', s);
        p.location.replace(url.toString());
      }}
    }}
  }} catch(e) {{}}
}})();
</script>""",
        height=0,
        scrolling=False,
    )


# ===========================================================
# PAGE PRINCIPALE
# ===========================================================



def main():
    _init_session()

    # ── Authentification ──────────────────────────────────────────────────────
    # Strategy: session_state + the _sid URL param (SQLite store).
    # The session is created in _finalize_login() and torn down by logout().
    from dashboard.auth import get_session, has_role, render_auth, logout, load_users_config
    session = get_session()
    # F5 robustness: if the session is valid but _sid is missing from the URL
    # (e.g. navigation without _sid), put it back at once so the next F5 works too.
    if session:
        _sid_in_state = st.session_state.get("_session_id", "")
        if _sid_in_state and not st.query_params.get("_sid"):
            st.query_params["_sid"] = _sid_in_state
    st.session_state["admin_authenticated"] = has_role(session, "back")
    st.session_state["username"] = session.get("username", "") if session else ""
    st.session_state["_suppress_auth_ui"] = bool(session)
    if has_role(session, "back"):
        # Prevents residual TOTP screens after a successful authentication.
        st.session_state.pop("_auth_step", None)
        st.session_state.pop("_auth_pending_user", None)
        st.session_state.pop("_auth_totp_new_secret", None)

    users_cfg = load_users_config()
    guest_mode = users_cfg.get("settings", {}).get("guest_mode", True)

    # JS localStorage - recovers the session even when _sid disappears from the URL.
    _inject_session_persistence_js(bool(session))

    _inject_theme_css()
    render_header()

    show_admin = st.query_params.get("admin", "0") == "1"

    if show_admin:
        # ── VUE ADMINISTRATION ──
        if not has_role(session, "back"):
            # All the auth content lives in a SINGLE clearable slot.
            # _render_totp_verify / _render_totp_setup appellent
            # use st.session_state['_auth_slot'].empty() before st.rerun()
            # to clear title + info + form atomically -> no artefact.
            _auth_slot = st.empty()
            st.session_state["_auth_slot"] = _auth_slot
            with _auth_slot.container():
                st.markdown(
                    f'<h3 style="margin:0 0 12px;font-size:18px;"><i class="fas fa-lock" '
                    f'style="margin-right:8px;color:#e74c3c;"></i>{t("admin_title")}</h3>',
                    unsafe_allow_html=True,
                )
                st.info(t("admin_auth_required"))
                render_auth()
            return
        else:
            render_admin_panel()
            return
    else:
        # ── VUE DASHBOARD ──
        if not guest_mode and not has_role(session, "front"):
            # Protected front office
            render_auth()
        else:
            # Auto-refresh handled by JS in the navbar (window.location.reload every 90s)
            # -> no Streamlit rerun, no greyed-out effect

            last_cycle = _get_last_cycle()
            portfolio  = _get_portfolio()          # consolidated (global view)
            _get_pnl_history()

            from dashboard.multi_asset import render_asset_tabs

            def _render_for_asset(asset: str):
                """Full render for one asset - V4 only."""
                _tr = _get_recent_trades(200, asset=asset)
                _pf = _get_portfolio(asset=asset)
                render_portfolio(_pf)
                render_trades_list_sortable(_tr)
                render_pnl_chart(_tr, key=f"pnl_chart_{asset.replace('/', '_')}")
                render_live_logs(key=asset.replace('/', '_'), asset=asset)

            def _render_portfolio_first():
                """Global portfolio - shown at the top of the Global view."""
                render_portfolio(portfolio)

            def _render_global():
                """Consolidated view: PnL across all assets."""
                st.markdown("---")
                _tr_all = _get_recent_trades(500)
                render_trades_list_sortable(_tr_all)
                render_pnl_chart(_tr_all, key="pnl_chart_global")
                render_live_logs(key="global")

            render_asset_tabs(_render_for_asset, global_fn=_render_global, pre_global_fn=_render_portfolio_first)

            # -- Live price poller (updates the Progression columns without a reload) --
            _inject_live_trade_prices_js()

            st.markdown(
                '<div style="text-align:center;padding:24px 0 8px;'
                'font-size:11px;opacity:0.35;">Atlas Trader &mdash; by Jako 2026</div>',
                unsafe_allow_html=True,
            )

if __name__ == "__main__":
    main()
