"""
dashboard/streamlit_app.py — Dashboard principal Atlas Trader
Interface User (lecture seule) + Interface Admin (protégée par mot de passe).
"""
from __future__ import annotations

import hashlib
import html
import sys
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from queue import Queue, Empty


def _fmt_utc_local(dt_utc: datetime) -> str:
    """Format 'DD/MM/YYYY HH:MM UTC (HH:MM local)' where local = Europe/Paris."""
    try:
        from zoneinfo import ZoneInfo
        local_tz = ZoneInfo("Europe/Paris")
    except Exception:
        local_tz = timezone(timedelta(hours=1))  # fallback UTC+1
    local_dt = dt_utc.replace(tzinfo=timezone.utc).astimezone(local_tz)
    return f"{dt_utc.strftime('%d/%m/%Y %H:%M')} UTC ({local_dt.strftime('%H:%M')} local)"

# Garantir que /app (ou le parent du dossier courant) est en tête du sys.path
# pour éviter les conflits avec des packages "utils" de dépendances tierces
_APP_ROOT = str(Path(__file__).resolve().parent.parent)
if _APP_ROOT not in sys.path:
    sys.path.insert(0, _APP_ROOT)


# Logo 34×34 extrait de atlas.ico (base64 PNG ~3KB — aucune dépendance fichier)
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

try:
    from dashboard.flux_manager import render_flux_manager_page
except Exception:
    from flux_manager import render_flux_manager_page
from utils.i18n import t, set_lang, get_lang, SUPPORTED_LANGS

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
        'integrity="sha512-Avb2QiuDEEvB4bZJYdft2mNjVShBftLdPG8FJ0V7irTLQ8Uo0qcPxh4Plq7G5tGm0rU+1SPhVotteLpBERwTkw==" '
        'crossorigin="anonymous">',
        # S6: SRI hash protège contre le remplacement de la CDN
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

    # CSS global pour les tooltips Streamlit (rendus dans body via portal React)
    # Toujours injecté — couleurs adaptées au thème courant
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
# CHARGEMENT DES DONNÉES
# ===========================================================

@st.cache_data(ttl=20)
def _get_recent_decisions(n: int = 50, asset: str | None = None) -> list[dict]:
    """Cache 20s — évite les requêtes SQLite redondantes lors de chaque rerun auto."""
    try:
        from storage.database import get_recent_decisions
        return get_recent_decisions(n, asset=asset)
    except Exception:
        return []


@st.cache_data(ttl=90)
def _get_live_indicators(asset: str) -> dict:
    """Indicateurs live avec cache 90s — TTL > autorefresh (60s) évite un appel réseau bloquant à chaque rerun."""
    try:
        from agents.market_data_agent import MarketDataAgent
        return MarketDataAgent().get_indicators(asset)
    except Exception:
        return {}


@st.cache_data(ttl=120)
def _get_ohlcv(asset: str) -> tuple[list, list]:
    """OHLCV 15m / 24h avec cache 2min — évite fetch_ohlcv bloquant à chaque rerun."""
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
    """P3: utilise get_recent_trades (filtre SQL) au lieu de charger 2000 lignes."""
    try:
        from storage.database import get_recent_trades
        return get_recent_trades(n, asset=asset)
    except Exception:
        return []


@st.cache_data(ttl=60)
def _get_portfolio(asset: str | None = None) -> dict:
    try:
        from execution.paper_trader import PaperTrader
        return PaperTrader().get_portfolio(asset=asset)
    except Exception:
        return {"capital": 10000, "current_value": 10000, "total_pnl": 0,
                "total_pnl_pct": 0, "n_trades": 0, "asset": asset or "ALL",
                "live_mode": False}


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
        import os
        from pathlib import Path
        settings_file = os.environ.get("SETTINGS_FILE")
        if settings_file:
            _cfg_path = Path(settings_file)
        else:
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
        import os
        from pathlib import Path
        # Respecte SETTINGS_FILE si défini (ex: settings.gx10.yaml sur GX10)
        settings_file = os.environ.get("SETTINGS_FILE")
        if settings_file:
            _cfg_path = Path(settings_file)
        else:
            _cfg_path = Path(__file__).parent.parent / "config" / "settings.yaml"
        save_settings(settings, _cfg_path)
        return True
    except Exception as _exc:
        import logging
        logging.getLogger("zeitgeist.dashboard").error(f"save_settings failed: {_exc}", exc_info=True)
        st.session_state["_save_error"] = str(_exc)
        return False


# ===========================================================
# COMPOSANTS UI USER
# ===========================================================

def _force_run_background(asset: str, log_q) -> None:
    """
    Exécute le cycle V2 depuis un thread background.
    Poste des chaînes HTML dans log_q au fur et à mesure.
    Poste ("__done__", (is_error: bool, message: str)) en dernier.
    """
    import time as _time
    import logging

    _logger = logging.getLogger("atlas.workflow")

    def _log(txt):
        log_q.put(txt)

    start_ts = _time.strftime("%Y-%m-%d %H:%M:%S")
    _logger.info(f"=== DASHBOARD FORCE-RUN V2 — {asset} @ {start_ts} ===")
    _log(f"🚀 <b>Démarrage cycle V2</b> — {asset} ({start_ts})")
    _log(f"⏳ <b>OHLCV → Features → Régime → Signal → Stratégie → Risk...</b>")

    t_total = _time.time()
    try:
        from graph.workflow import run_cycle
        result = run_cycle(asset=asset, trigger="force")
        total_s = _time.time() - t_total

        action   = result.get("action", "N/A").upper()
        prob_up  = result.get("prob_up")
        regime   = "TREND" if result.get("regime_trending") else "RANGE"
        capital  = result.get("capital", 0)
        close    = result.get("close_price", 0)
        reason   = result.get("reason", "")
        errors   = result.get("errors", [])
        pos      = result.get("position")

        _log(f"✅ <b>Pipeline OK</b> — {total_s:.1f}s")
        _log(
            f"📊 Prix: <b>${close:,.2f}</b> | Régime: <b>{regime}</b> | "
            f"P(up): <b>{f'{prob_up:.3f}' if prob_up is not None else 'N/A'}</b>"
        )
        _log(f"🎯 Décision: <b>{action}</b> — {reason}")
        if pos:
            _log(
                f"📌 Position: <b>{pos.get('side','?').upper()}</b> "
                f"@ {pos.get('entry_price',0):,.2f} | "
                f"SL={pos.get('sl',0):,.2f} TP={pos.get('tp',0):,.2f}"
            )
        _log(f"💰 Capital: <b>${capital:,.0f}</b>")

        if errors:
            for e in errors:
                _log(f"⚠️ {e}")
            msg = f"Cycle V2 terminé ({len(errors)} avertissement(s)) — {action} | {total_s:.1f}s"
            log_q.put(("__done__", (False, msg)))
        else:
            msg = f"Cycle V2 OK — {action} | capital ${capital:,.0f} | {total_s:.1f}s"
            log_q.put(("__done__", (False, msg)))

    except Exception as exc:
        total_s = _time.time() - t_total
        _logger.exception(f"Force-run V2 échoué: {exc}")
        _log(f"❌ <b>Erreur cycle V2</b> — {exc} ({total_s:.1f}s)")
        log_q.put(("__done__", (True, f"Erreur: {exc}")))


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

    # ── Première entrée ── acquérir le lock et démarrer le thread ──────────
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

    # ── Afficher les logs accumulés ──────────────────────────────────────────
    log_c = st.container()
    for msg in s["logs"]:
        log_c.markdown(msg, unsafe_allow_html=True)

    # ── Terminé ou encore en cours ───────────────────────────────────────────
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
            cfg   = _get_settings()
            st.session_state["_force_run_asset"] = cfg.get("project", {}).get("asset", "BTC/USDT")
        # else: silently ignore — unauthenticated users cannot trigger a cycle

    if st.session_state.get("admin_authenticated") and st.session_state.get("_force_run_asset"):
        _force_run_dialog(st.session_state["_force_run_asset"])

    # ─ URLs ─────────────────────────────────────────────────────────────────
    adm   = "1" if show_admin else "0"
    _sid = st.query_params.get("_sid", "") or st.session_state.get("_session_id", "")
    sid_q = f"&_sid={_sid}" if _sid else ""
    # Garder _sid dans les URLs pour conserver la session après refresh/navigation
    m_open  = f"lang={lang_param}&theme={theme}&admin={adm}&menu=1{sid_q}"
    m_close = f"lang={lang_param}&theme={theme}&admin={adm}&menu=0{sid_q}"
    base    = f"lang={lang_param}&theme={theme}&admin={adm}&menu=0{sid_q}"
    u_refresh  = f"?_action=refresh&{base}"
    u_force    = f"?_action=force_run&{base}"
    u_hamburger = f"?{m_close if menu_open else m_open}"
    # menu items (chaque clic ferme le menu)
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
    # _cycle_locked : un cycle est ACTIF en ce moment (lock posé)
    # _daemon_alive : daemon vivant (heartbeat < 30 min) mais pas forcément en train de cycler
    from utils.cycle_lock import is_locked as _cycle_is_locked
    _cycle_locked = _cycle_is_locked()
    _daemon_alive = _cycle_locked
    if not _daemon_alive:
        # V2 : vérifier l'ancienneté de v2_state.updated_at (< 30 min = daemon actif)
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

    # Bouton Force Run : visible seulement pour les admins authentifiés
    _bolt_cls  = 'atlas-bolt-active' if _cycle_locked else ('atlas-bolt-alive' if _daemon_alive else '')
    bolt_html  = (f'<a href="{u_force}" style="{S_BTN}" title="Force Run" target="_self"'
                  f' class="{_bolt_cls}"><i class="fas fa-bolt"></i></a>'
                  if st.session_state.get('admin_authenticated') else '')

    # ─ Dropdown HTML (rendu seulement si menu_open) ─────────────────────────
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
    # Auto-refresh toutes les 15s quand un cycle tourne → arrêt auto quand fini
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
  {bolt_html}
  <a href="{u_hamburger}" style="{S_HBG}" title="Menu" target="_self"><i class="fas fa-bars"></i></a>
</nav>
{dropdown_html}
<script>
  (function(){{
    if(!window._atlasAutoRefresh){{
      window._atlasAutoRefresh=true;
      setTimeout(function(){{window.location.reload();}},90000);
    }}
  }})();
</script>
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
    import glob as _cm_glob, os as _cm_os, time as _cm_time
    from utils.cycle_lock import is_locked as _is_cycle_locked

    theme  = _get_theme()
    score  = last_cycle.get("score",  50) if last_cycle else 50
    action = last_cycle.get("action", "—") if last_cycle else "—"
    ts     = last_cycle.get("timestamp", "") if last_cycle else ""
    asset  = (last_cycle.get("asset", "") if last_cycle else "").replace("/", "_")

    # Fallback V2 : si aucune donnée V1, lire v2_state pour action + timestamp
    if action == "—":
        try:
            from storage.database import get_v2_state as _gv2s
            _v2 = _gv2s()
            if _v2:
                _v2_raw = (_v2.get("action") or "flat").upper()
                action = _v2_raw  # LONG / SHORT / FLAT
                ts = _v2.get("updated_at", "")
                if not asset:
                    asset = (_v2.get("asset", "")).replace("/", "_")
        except Exception:
            pass

    time_ago = "—"
    if ts:
        try:
            diff = int((datetime.utcnow() - datetime.fromisoformat(ts)).total_seconds() / 60)
            time_ago = f"V2 {diff} min" if diff < 60 else f"V2 {diff // 60} h"
        except Exception:
            pass

    # Indicateur propre à l'asset :
    #  - ⟳ en cours  : lock actif pour cet asset
    #  - ✓ actif     : heartbeat de cet asset < 30 min (cycles récents)
    #  - 🌙 hors session : heartbeat de cet asset > 30 min (forex fermé, etc.)
    _asset_hb = f"/tmp/atlas_heartbeat_{asset}" if asset else None
    _asset_slash = asset.replace("_", "/") if asset else None
    if _is_cycle_locked(_asset_slash):
        time_ago += f' <span style="color:#22c55e;font-size:11px;">{t("status_running")}</span>'
    elif _asset_hb and _cm_os.path.exists(_asset_hb):
        _hb_age = _cm_time.time() - _cm_os.path.getmtime(_asset_hb)
        if _hb_age < 1800:
            time_ago += f' <span style="color:#22c55e;font-size:11px;">{t("status_active")}</span>'
        else:
            # Calcul heure de reprise via MarketSession
            _next_label = ""
            _is_crypto = False
            try:
                from utils.session import MarketSession as _MarketSession, _get_profile as _sess_prof
                _sess = _MarketSession(_asset_slash or "BTC/USDT")
                _is_crypto = (_sess_prof(_asset_slash or "BTC/USDT") == "crypto")
                _nxt = _sess.next_open()
                _nxt_utc = _nxt.strftime("%H:%M UTC")
                _wait_min = int((_nxt - __import__('datetime').datetime.now(
                    __import__('datetime').timezone.utc)).total_seconds() / 60)
                if _wait_min < 60:
                    _next_label = t("status_resumes_in_min").format(n=_wait_min, time=_nxt_utc)
                elif _wait_min < 1440:
                    _next_label = t("status_resumes_at").format(time=_nxt_utc)
                else:
                    _nxt_day = _nxt.strftime("%a %H:%M UTC")
                    _next_label = t("status_resumes_day").format(day=_nxt_day)
            except Exception:
                pass
            # Pour crypto (24/7), "hors session" n'a pas de sens → "daemon inactif"
            if _is_crypto:
                _hb_age_h = int(_hb_age / 3600)
                _hb_age_m = int((_hb_age % 3600) / 60)
                _age_str = f"{_hb_age_h}h{_hb_age_m:02d}" if _hb_age_h else f"{_hb_age_m}min"
                time_ago += (
                    f' <span style="color:#f39c12;font-size:11px;">'
                    f'⚠️ daemon inactif depuis {_age_str}</span>'
                )
            else:
                time_ago += (
                    f' <span style="color:#888;font-size:11px;">'
                    f'{t("status_off_session")}{_next_label}</span>'
                )

    act_map = {
        "BUY":   ("#2ecc71", "fas fa-arrow-trend-up"),
        "SELL":  ("#e74c3c", "fas fa-arrow-trend-down"),
        "HOLD":  ("#f39c12", "fas fa-hand"),
        "LONG":  ("#2ecc71", "fas fa-arrow-trend-up"),
        "SHORT": ("#e74c3c", "fas fa-arrow-trend-down"),
        "FLAT":  ("#888888", "fas fa-minus"),
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


def render_v2_quant_state(asset: str | None = None):
    """
    Bloc V2 Quant — régime, P(up), décision, position ouverte, courbe equity.
    S'intègre dans le dashboard principal avec le même style de cartes.
    Silencieux si la DB V2 n'a pas encore de données.
    """
    try:
        from storage.database import get_v2_state, get_v2_equity_curve
        import plotly.graph_objects as _go
    except Exception:
        return

    state = get_v2_state()
    if not state:
        return  # Premier démarrage — rien à afficher encore

    theme = _get_theme()
    bg, bdr, txt, muted, ic = _card_colors(theme)
    kw = dict(bg=bg, bdr=bdr, txt=txt, muted=muted, ic=ic)

    # ── Titre section ──────────────────────────────────────────────────────────
    st.markdown(
        '<h3 style="margin:20px 0 10px;font-size:18px;">'
        '<i class="fas fa-microchip" style="margin-right:8px;color:#7986cb;"></i>'
        + t("v2_quant_title", lang=None) + '</h3>',
        unsafe_allow_html=True,
    )

    # ── Cartes : Régime / P(up) / Décision V2 / Capital V2 ───────────────────
    regime_val = state.get("regime")
    if regime_val is None:
        regime_label = "N/A"
        regime_color = "#888"
    elif regime_val in (1, 1.0):
        regime_label = "TRENDING"
        regime_color = "#2ecc71"
    elif regime_val == 0.5:
        regime_label = "RANGING"
        regime_color = "#f39c12"
    else:
        regime_label = "PANIC"
        regime_color = "#e74c3c"

    prob_up = state.get("prob_up")
    if prob_up is not None:
        prob_pct = f"{prob_up:.1%}"
        if prob_up > 0.55:
            prob_color = "#2ecc71"
            prob_delta = "> 0.55 — signal haussier"
            prob_d_pos = True
        elif prob_up < 0.45:
            prob_color = "#e74c3c"
            prob_delta = "< 0.45 — signal baissier"
            prob_d_pos = False
        else:
            prob_color = "#f39c12"
            prob_delta = "zone morte [0.45 – 0.55]"
            prob_d_pos = None
    else:
        prob_pct, prob_color, prob_delta, prob_d_pos = "N/A", "#888", None, None

    action_v2 = (state.get("action") or "flat").upper()
    act_v2_color = {"LONG": "#2ecc71", "SHORT": "#e74c3c"}.get(action_v2, "#888")
    act_v2_fa = {"LONG": "fas fa-arrow-trend-up", "SHORT": "fas fa-arrow-trend-down"}.get(
        action_v2, "fas fa-minus")
    reason_v2 = state.get("reason", "")

    cap_v2 = state.get("capital")
    cap_v2_html = f'${cap_v2:,.0f}' if cap_v2 is not None else "N/A"

    grid = (
        _html_card("fas fa-wave-square", t("v2_regime"),
                   f'<span style="color:{regime_color}">{regime_label}</span>',
                   **kw) +
        _html_card("fas fa-percent", t("v2_prob_up"),
                   f'<span style="color:{prob_color}">{prob_pct}</span>',
                   delta=prob_delta, d_pos=prob_d_pos, **kw) +
        _html_card(act_v2_fa, t("v2_decision"),
                   f'<span style="color:{act_v2_color}">{action_v2}</span>',
                   delta=reason_v2 or None, d_pos=None, **kw) +
        _html_card("fas fa-wallet", t("v2_capital"),
                   cap_v2_html, **kw)
    )
    st.markdown(
        f'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));'
        f'gap:12px;margin-bottom:12px;">{grid}</div>',
        unsafe_allow_html=True,
    )

    # ── Position ouverte ──────────────────────────────────────────────────────
    pos_side = state.get("position_side")
    if pos_side:
        entry = state.get("entry_price")
        sl    = state.get("sl_price")
        tp    = state.get("tp_price")
        close = state.get("close_price")
        pnl_pct = None
        if entry and close:
            pnl_pct = (close - entry) / entry if pos_side == "long" else (entry - close) / entry
        pnl_col = "#2ecc71" if (pnl_pct or 0) >= 0 else "#e74c3c"
        pnl_str = f"{pnl_pct:+.2%}" if pnl_pct is not None else "—"
        pos_html = (
            f'<div style="background:{bg};border:1px solid {bdr};border-radius:10px;'
            f'padding:10px 14px;font-size:13px;margin-bottom:10px;">'
            f'<b style="color:{"#2ecc71" if pos_side=="long" else "#e74c3c"}">'
            f'{"▲" if pos_side=="long" else "▼"} {pos_side.upper()}</b>'
            f'&nbsp;·&nbsp; Entry <b>${entry:,.2f}</b>'
            f'&nbsp;·&nbsp; SL <b style="color:#e74c3c">${sl:,.2f}</b>'
            f'&nbsp;·&nbsp; TP <b style="color:#2ecc71">${tp:,.2f}</b>'
            f'&nbsp;·&nbsp; P&L latent <b style="color:{pnl_col}">{pnl_str}</b>'
            f'</div>'
        ) if entry and sl and tp else ""
        if pos_html:
            st.markdown(pos_html, unsafe_allow_html=True)

    # ── Courbe equity V2 (compacte) ───────────────────────────────────────────
    equity_rows = get_v2_equity_curve(n=200)
    if equity_rows and len(equity_rows) >= 2:
        import pandas as _pd
        eq_df = _pd.DataFrame(equity_rows)
        eq_df["ts"] = _pd.to_datetime(eq_df["ts"])
        eq_df = eq_df.sort_values("ts")

        fig = _go.Figure()
        fig.add_trace(_go.Scatter(
            x=eq_df["ts"], y=eq_df["equity"],
            mode="lines", name=t("v2_equity"),
            line=dict(color="#4fc3f7", width=2),
            fill="tozeroy", fillcolor="rgba(79,195,247,0.06)",
        ))
        entries = eq_df[eq_df["action"].isin(["long", "short"])]
        if not entries.empty:
            fig.add_trace(_go.Scatter(
                x=entries["ts"], y=entries["equity"],
                mode="markers",
                marker=dict(
                    size=7,
                    color=entries["action"].map({"long": "#2ecc71", "short": "#e74c3c"}),
                    symbol=entries["action"].map({"long": "triangle-up", "short": "triangle-down"}),
                ),
                name=t("v2_entries"),
            ))
        fig.update_layout(
            height=200, margin=dict(l=0, r=0, t=6, b=0),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(showgrid=False, color=muted),
            yaxis=dict(showgrid=True, gridcolor=bdr, color=muted),
            legend=dict(orientation="h", y=1.1, font=dict(color=muted, size=11)),
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True, key=f"v2_equity_{asset or 'all'}")

        # Métriques synthétiques inline
        if len(eq_df) >= 5:
            init = float(eq_df["equity"].iloc[0])
            final = float(eq_df["equity"].iloc[-1])
            total_ret = (final - init) / init
            rets = eq_df["equity"].pct_change().dropna()
            sharpe = float(rets.mean() / rets.std() * (365 * 96) ** 0.5) if rets.std() > 0 else 0.0
            cummax = eq_df["equity"].cummax()
            max_dd = float(((eq_df["equity"] - cummax) / cummax).min())
            col_r, col_s, col_d = st.columns(3)
            col_r.metric(t("v2_total_ret"),  f"{total_ret:+.2%}")
            col_s.metric(t("v2_sharpe"),     f"{sharpe:.2f}")
            col_d.metric(t("v2_max_dd"),     f"{max_dd:.2%}")

    # ── F.2 Monitoring live — détection de dégradation (3/3 IA, GPT : CRITIQUE) ───────
    _render_v2_monitoring(state, theme, bg, bdr, txt, muted)


def _render_v2_monitoring(state: dict, theme: str, bg: str, bdr: str, txt: str, muted: str) -> None:
    """Section monitoring : 6 indicateurs de dégradation en production."""
    try:
        from storage.database import get_v2_equity_curve, get_v2_state_history
        import pandas as _pd
    except Exception:
        return

    # Charger les 500 dernières barres d'equity + d'état pour les métriques rolling
    equity_rows = get_v2_equity_curve(n=500)
    if not equity_rows or len(equity_rows) < 20:
        return

    eq_df = _pd.DataFrame(equity_rows)
    eq_df["ts"] = _pd.to_datetime(eq_df["ts"])
    eq_df = eq_df.sort_values("ts").reset_index(drop=True)

    # 1. Rolling Sharpe 30 jours (288 barres × 5m = 30j à 5m)
    window_30d = min(288 * 30, len(eq_df))
    rets_roll = eq_df["equity"].pct_change().dropna()
    if len(rets_roll) >= 20:
        r_win = rets_roll.iloc[-window_30d:]
        rolling_sharpe = float(r_win.mean() / r_win.std() * (365 * 288) ** 0.5) if r_win.std() > 0 else 0.0
    else:
        rolling_sharpe = 0.0

    # 2. Distribution P(up) — dérive par rapport à la moyenne historique
    prob_up_current = state.get("prob_up")

    # 3. Ratio régime TRENDING (depuis l'état courant uniquement)
    regime_current = state.get("regime")
    regime_label = "TRENDING" if regime_current in (1, 1.0) else ("RANGING" if regime_current == 0.5 else ("PANIC" if regime_current is not None else "N/A"))

    # 4. Profit Factor rolling sur les 50 dernières actions
    actions_50 = eq_df["action"].iloc[-50:] if "action" in eq_df.columns else _pd.Series([], dtype=str)
    rets_50 = eq_df["equity"].pct_change().iloc[-50:].dropna()
    if len(rets_50) >= 5:
        wins = rets_50[rets_50 > 0].sum()
        losses = abs(rets_50[rets_50 < 0].sum())
        pf_rolling = float(wins / losses) if losses > 0 else float("inf")
    else:
        pf_rolling = None

    # 5. Brier score proxy — |P(up) - 0.5| moyen (signal de conviction)
    # (score de calibration approximatif sans cible connue)
    if prob_up_current is not None:
        conviction = abs(prob_up_current - 0.5)
    else:
        conviction = None

    # ── Rendu des alertes ────────────────────────────────────────────────────
    alerts = []
    if rolling_sharpe < 0:
        alerts.append(("🔴", f"Sharpe rolling 30j négatif ({rolling_sharpe:.2f}) — edge possiblement disparu"))
    elif rolling_sharpe < 0.3:
        alerts.append(("🟠", f"Sharpe rolling 30j faible ({rolling_sharpe:.2f}) — surveiller"))

    if prob_up_current is not None and abs(prob_up_current - 0.5) < 0.01:
        alerts.append(("🟠", f"P(up) ≈ 0.50 ({prob_up_current:.3f}) — signal neutre, edge possiblement perdu"))

    if pf_rolling is not None and pf_rolling < 1.0:
        alerts.append(("🔴", f"Profit Factor rolling 50 barres < 1.0 ({pf_rolling:.2f}) — pertes nettes récentes"))

    st.markdown(
        '<h4 style="margin:18px 0 8px;font-size:14px;color:' + muted + ';">'
        '<i class="fas fa-heartbeat" style="margin-right:6px;color:#e74c3c;"></i>'
        'Monitoring live — indicateurs de dégradation</h4>',
        unsafe_allow_html=True,
    )

    col1, col2, col3, col4 = st.columns(4)
    sharpe_color = "#2ecc71" if rolling_sharpe >= 0.5 else ("#f39c12" if rolling_sharpe >= 0 else "#e74c3c")
    col1.metric("Sharpe 30j", f"{rolling_sharpe:.2f}",
                delta="OK" if rolling_sharpe >= 0 else "ALERTE",
                delta_color="normal" if rolling_sharpe >= 0 else "inverse")
    col2.metric("P(up) actuel", f"{prob_up_current:.3f}" if prob_up_current else "N/A",
                delta=f"conv={conviction:.3f}" if conviction is not None else None)
    col3.metric(t("metric_current_regime"), regime_label)
    col4.metric("PF rolling 50", f"{pf_rolling:.2f}" if pf_rolling else "N/A",
                delta="OK" if pf_rolling and pf_rolling >= 1.2 else "bas",
                delta_color="normal" if pf_rolling and pf_rolling >= 1.2 else "inverse")

    if alerts:
        for icon, msg in alerts:
            st.warning(f"{icon} {msg}")


def render_portfolio(portfolio: dict):
    """Portefeuille paper en cartes Bootstrap-like avec Font Awesome."""
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
    """Modal : logique complète + traçabilité des poids pour un trade."""
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

    # ── Récupération du contexte ────────────────────────────────────────────────
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
    # Montre la décomposition exacte : score = Σ composante × poids
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

            # Détail des agents dans la composante "agents"
            agents_comp = eff_w.get("agents", {})
            agent_weights_in_comp = agents_comp.get("agent_weights", {})
            agent_detail_scores   = agents_comp.get("detail", {})
            if agent_weights_in_comp or agent_detail_scores:
                st.markdown("---")
                st.caption("**Poids individuels des agents dans la composante IA**")
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
            st.caption("Données de formule non disponibles pour ce trade.")
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
                            st.caption("Pas de résumé disponible pour cet agent.")
        else:
            st.caption("Scores agents non disponibles.")

    # ── Tab Marché ──────────────────────────────────────────────────────────────
    with tab_mkt:
        mkt = ctx.get("market") or {}
        rgm = ctx.get("regime") or {}
        if not isinstance(rgm, dict):
            rgm = {"state": str(rgm)}

        if rgm:
            c1, c2, c3 = st.columns(3)
            c1.metric("Régime", str(rgm.get("state", rgm.get("hmm_regime", "—"))))
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
            st.caption("Indicateurs de marché non disponibles.")

    # ── Tab Décision ────────────────────────────────────────────────────────────
    with tab_dec:
        dec   = ctx.get("decision") or {}
        s_val = dec.get("score") if dec.get("score") is not None else score
        buy_thr  = dec.get("buy_threshold", "—")
        exit_thr = dec.get("exit_threshold", "—")

        c1, c2, c3 = st.columns(3)
        c1.metric("Score final", f"{float(s_val):.1f}/100" if s_val is not None else "—")
        c2.metric("Seuil BUY", str(buy_thr))
        c3.metric("Seuil SELL", str(exit_thr))

        reasoning = dec.get("reasoning", "")
        if reasoning:
            st.markdown("---")
            st.code(reasoning, language=None)

        blockers = []
        if dec.get("ma50_blocked"):    blockers.append("🚫 MA50")
        if dec.get("funding_blocked"): blockers.append("🚫 Funding rate")
        if dec.get("cooldown"):        blockers.append("⏸ Cooldown")
        if blockers:
            st.warning("Bloqué : " + "  |  ".join(blockers))

    # ── Tab IA ──────────────────────────────────────────────────────────────────
    with tab_ia:
        if expl:
            st.markdown(
                f"<div style='font-size:12px;line-height:1.6'>{expl}</div>",
                unsafe_allow_html=True,
            )
        else:
            st.caption("Pas d'explication IA pour ce trade.")

        # ── Débat Bull/Bear (si disponible dans decision_context) ──────────────
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
            st.markdown("**🥊 Débat Bull/Bear**")
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
    # Marqueurs BUY/SELL avec contexte de décision en tooltip
    if "action" in df.columns:
        buys = df[df["action"] == "BUY"]
        sells = df[df["action"] == "SELL"]

        def _build_ctx(row: dict, hist_idx: int) -> list:
            """Extrait les champs clés de decision_context pour customdata Plotly."""
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
                hist_idx,     # [9] ← index dans history[] pour le dialog
            ]

        _hover_buy = (
            "<b>▲ BUY — %{customdata[0]}</b><br>"
            "Date : %{x|%Y-%m-%d %H:%M}<br>"
            "P&L cumulé : %{y:+.2f}$<br>"
            "Entry : %{customdata[2]}<br>"
            "Score : %{customdata[3]} | Régime : %{customdata[4]}<br>"
            "RSI : %{customdata[5]} | MACD : %{customdata[6]}<br>"
            "Agents : %{customdata[7]}<br>"
            "<i style='opacity:0.6'>🖱 Cliquer pour le détail complet</i>"
            "<extra></extra>"
        )
        _hover_sell = (
            "<b>▼ SELL — %{customdata[0]}</b><br>"
            "Date : %{x|%Y-%m-%d %H:%M}<br>"
            "P&L cumulé : %{y:+.2f}$<br>"
            "P&L position : %{customdata[1]}<br>"
            "Entry : %{customdata[2]}<br>"
            "Score : %{customdata[3]} | Régime : %{customdata[4]}<br>"
            "RSI : %{customdata[5]} | MACD : %{customdata[6]}<br>"
            "Agents : %{customdata[7]}<br>"
            "<i style='opacity:0.6'>🖱 Cliquer pour le détail complet</i>"
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
    # Ouvrir le dialog si un marqueur BUY/SELL est cliqué
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


def render_live_chart(asset: str = "BTC/USDT"):
    """Graphique prix en temps réel avec niveaux SL/TP des positions ouvertes."""
    st.markdown(f'<h3 style="margin:0 0 12px;font-size:18px;"><i class="fas fa-satellite-dish" style="margin-right:8px;color:#7986cb;"></i>{asset} — {t("open_pos_label")}</h3>', unsafe_allow_html=True)

    try:
        from storage.database import get_recent_decisions
        indicators = _get_live_indicators(asset)
        current_price = indicators.get("price", 0)
        ma_50 = indicators.get("ma_50", 0)

        open_pos = [
            d for d in get_recent_decisions(500, asset=asset)
            if d.get("action") == "BUY" and d.get("result_24h") is None
        ]
    except Exception as exc:
        st.warning(f'{t("data_load_error")} : {exc}')
        return

    if not open_pos:
        c1, c2, c3 = st.columns(3)
        c1.metric(f"Prix {asset.split('/')[0]}", f"${current_price:,.2f}" if current_price else "—")
        if ma_50:
            c2.metric("MA50", f"${ma_50:,.2f}",
                      delta=f"{(current_price/ma_50-1)*100:+.1f}%" if current_price and ma_50 else None,
                      delta_color="normal")
        c3.metric(t("open_pos_label"), "0")

        # Graphique prix 24h même sans positions
        try:
            times, closes = _get_ohlcv(asset)
            if times and closes:
                fig_empty = go.Figure()
                fig_empty.add_trace(go.Scatter(
                    x=pd.to_datetime(times, unit="ms"),
                    y=closes,
                    mode="lines",
                    line=dict(color="#00d4ff", width=2),
                    name=asset,
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
                st.plotly_chart(fig_empty, use_container_width=True, key=f"live_chart_empty_{asset.replace('/', '_')}")
            else:
                st.info(t("no_open_pos"))
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
    c1.metric(f"Prix {asset.split('/')[0]}", f"${current_price:,.2f}" if current_price else "—")
    if ma_50:
        c2.metric("MA50", f"${ma_50:,.2f}",
                  delta=f"{(current_price/ma_50-1)*100:+.1f}%" if current_price else None,
                  delta_color="normal")
    c3.metric(t("open_pos_label"), n_open)
    st.plotly_chart(fig, use_container_width=True, key=f"live_chart_{asset.replace('/', '_')}")


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
        if action == "SELL":
            # SELL = signal de sortie (long-only) — le P&L est sur la ligne BUY d'origine
            pnl_str   = f'<span style="opacity:.6;font-style:italic;">✓ Clôture</span>'
        elif pnl is None:
            pnl_str   = f'<span style="opacity:.45;">{t("pending")}</span>'
        elif pnl >= 0:
            pnl_str   = f'<span style="color:#2ecc71;font-weight:600;">${pnl:+,.2f}</span>'
        else:
            pnl_str   = f'<span style="color:#e74c3c;font-weight:600;">${pnl:+,.2f}</span>'

        cells = [
            trade.get("timestamp", "")[:16].replace("T", " "),
            f'<span style="color:{action_color};font-weight:600;">{action}</span>',
            f'${trade.get("entry_price", 0):,.2f}' if trade.get("entry_price") else "—",
            f'${(trade.get("position_size_usd") if trade.get("position_size_usd") is not None else trade.get("position_size", 0)):,.0f}'
                if (trade.get("position_size_usd") is not None or trade.get("position_size")) else "—",
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
            border-radius:10px;background:{tbl_bg};margin-bottom:24px;">
  <table style="border-collapse:collapse;width:100%;min-width:700px;">
    <thead><tr>{header_cells}</tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>"""
    st.markdown(html, unsafe_allow_html=True)


@st.fragment
def render_trades_list_sortable(trades: list[dict]):
    """Historique global des trades — triable et cliquable pour voir le détail."""
    st.markdown(
        f'<h3 style="margin:16px 0 12px;font-size:18px;">'
        f'<i class="fas fa-clock-rotate-left" style="margin-right:8px;color:#7986cb;"></i>'
        f'{t("trades_all_title")}</h3>',
        unsafe_allow_html=True,
    )
    if not trades:
        st.info(t("no_trades"))
        return

    col_date   = t("col_date")
    col_asset  = t("col_asset")
    col_action = t("col_action")
    col_entry  = t("col_entry")
    col_size   = t("col_size_usd")
    col_pnl    = t("col_pnl")
    col_score  = t("col_score")

    import json as _json_tr
    rows = []
    for trade in trades:
        pnl    = trade.get("result_24h")
        action = trade.get("action", "")
        # Extraire signal_detail depuis decision_context
        _sig_detail = ""
        _raw_dc = trade.get("decision_context")
        if _raw_dc:
            try:
                _dc = _json_tr.loads(_raw_dc) if isinstance(_raw_dc, str) else _raw_dc
                _sig_detail = ((_dc.get("agents") or {}).get("synthesis") or {}).get("signal_detail") or ""
            except Exception:
                pass
        rows.append({
            col_date:   trade.get("timestamp", "")[:16].replace("T", " "),
            col_asset:  trade.get("asset", "—"),
            col_action: action,
            "Signal":   _sig_detail,
            col_entry:  trade.get("entry_price"),
            col_size:   trade.get("position_size_usd") if trade.get("position_size_usd") is not None else trade.get("position_size"),
            "SL":       trade.get("sl_price"),
            "TP":       trade.get("tp_price"),
            col_pnl:    pnl,
            col_score:  trade.get("score"),
        })

    df = pd.DataFrame(rows)

    def _action_color(v):
        if v == "BUY":  return "color: #2ecc71; font-weight: bold"
        if v == "SELL": return "color: #e74c3c; font-weight: bold"
        return ""

    def _signal_color(v):
        if v in ("STRONG_BUY",):  return "color: #00e676; font-weight: 700"
        if v in ("BUY",):         return "color: #69f0ae"
        if v in ("HOLD",):        return "color: #ffb74d"
        if v in ("SELL",):        return "color: #ef9a9a"
        if v in ("STRONG_SELL",): return "color: #e53935; font-weight: 700"
        return "opacity: 0.4"

    def _pnl_color(v):
        try:
            return "color: #2ecc71; font-weight: 600" if float(v) >= 0 else "color: #e74c3c; font-weight: 600"
        except Exception:
            return ""

    styled = (
        df.style
        .map(_action_color, subset=[col_action])
        .map(_signal_color, subset=["Signal"])
        .map(_pnl_color, subset=[col_pnl])
    )

    st.caption(t("click_row_detail"))
    event = st.dataframe(
        styled,
        use_container_width=True,
        height=min(480, 36 * (len(trades) + 2)),
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            col_entry: st.column_config.NumberColumn(format="$%.2f"),
            col_size:  st.column_config.NumberColumn(format="$%.0f"),
            "SL":      st.column_config.NumberColumn(format="$%.2f"),
            "TP":      st.column_config.NumberColumn(format="$%.2f"),
            col_pnl:   st.column_config.NumberColumn(format="$%.2f"),
            col_score: st.column_config.NumberColumn(format="%.0f /100"),
        },
    )

    selected_rows = []
    try:
        selected_rows = event.selection.rows or []
    except Exception:
        pass
    if selected_rows:
        idx = selected_rows[0]
        if 0 <= idx < len(trades):
            _show_trade_detail_dialog(trades[idx])


def render_last_decision(last_cycle: dict | None):
    """Affiche la dernière décision V2 (depuis v2_state, pas la table V1 decisions)."""
    st.markdown('<div style="margin-top:24px;"></div>', unsafe_allow_html=True)
    st.markdown(f'<h3 style="margin:0 0 12px;font-size:18px;"><i class="fas fa-chart-bar" style="margin-right:8px;color:#7986cb;"></i>{t("last_decision_title")}</h3>', unsafe_allow_html=True)

    # V2 : lire directement v2_state (la table decisions V1 n'est plus alimentée)
    try:
        from storage.database import get_v2_state
        state = get_v2_state()
    except Exception:
        state = None

    if not state:
        st.info(t("no_cycle"))
        return

    action = (state.get("action") or "flat").upper()
    action_color = {"LONG": "#2ecc71", "SHORT": "#e74c3c", "FLAT": "#888888"}.get(action, "#888888")
    explanation = state.get("reason") or "—"

    # Formatage de la date/heure (depuis v2_state.updated_at)
    _ld_updated = state.get("updated_at") or ""
    ts_label = ""
    if _ld_updated:
        try:
            dt = datetime.fromisoformat(_ld_updated)
            ts_label = _fmt_utc_local(dt)
        except Exception:
            ts_label = _ld_updated[:16]

    prob_up    = state.get("prob_up")
    regime_raw = state.get("regime")
    regime_str = "TREND" if regime_raw in (1, 1.0) else ("RANGE" if regime_raw == 0.5 else ("PANIC" if regime_raw is not None else "—"))
    close_price = state.get("close_price")
    atr_14      = state.get("atr_14")
    model_fit_at = state.get("model_fit_at")

    # Carte action principale
    st.markdown(
        f"<div style='border-left:4px solid {action_color};padding:12px 16px;border-radius:4px;"
        f"background:rgba(255,255,255,0.03);'>"
        f"<strong style='color:{action_color};font-size:20px;'>{action}</strong>"
        + (f" &nbsp;<span style='font-size:11px;opacity:0.5;'>🕐 {ts_label}</span>" if ts_label else "")
        + "<br><span style='font-size:11px;opacity:0.55;'>Pipeline V2 quantitatif pur</span>"
        + f"<br><br><b>Raison :</b> <code style='font-size:12px;'>{explanation}</code>"
        + (f"<br><b>Régime :</b> {regime_str} &nbsp;·&nbsp; <b>P(↑) :</b> {prob_up:.3f}" if prob_up is not None else "")
        + (f"<br><b>Prix clôture :</b> <b>${close_price:,.2f}</b>" if close_price else "")
        + (f" &nbsp;·&nbsp; <b>ATR(14) :</b> ${atr_14:.2f}" if atr_14 else "")
        + "</div>",
        unsafe_allow_html=True,
    )

    # Position ouverte (si présente)
    _ld_pos = state.get("position_side")
    if _ld_pos:
        _ld_entry = state.get("entry_price")
        _ld_sl    = state.get("sl_price")
        _ld_tp    = state.get("tp_price")
        _ld_pcol  = "#2ecc71" if _ld_pos == "long" else "#e74c3c"
        _ld_arrow = "▲" if _ld_pos == "long" else "▼"
        st.markdown(
            f"<div style='margin-top:8px;padding:8px 12px;border-radius:6px;"
            f"background:rgba(255,255,255,0.04);font-size:13px;'>"
            f"<b style='color:{_ld_pcol}'>{_ld_arrow} {_ld_pos.upper()}</b>"
            + (f" @ <b>${_ld_entry:,.2f}</b>" if _ld_entry else "")
            + (f" &nbsp;·&nbsp; SL <b style='color:#e74c3c'>${_ld_sl:,.2f}</b>" if _ld_sl else "")
            + (f" &nbsp;·&nbsp; TP <b style='color:#2ecc71'>${_ld_tp:,.2f}</b>" if _ld_tp else "")
            + "</div>",
            unsafe_allow_html=True,
        )

    # Date refit modèle
    if model_fit_at:
        try:
            fit_dt  = datetime.fromisoformat(model_fit_at)
            age_h   = int((datetime.utcnow() - fit_dt).total_seconds() / 3600)
            age_str = f"{age_h}h" if age_h < 48 else f"{age_h // 24}j"
            st.caption(f"🧠 Modèle refit il y a {age_str}")
        except Exception:
            pass


_LOGS_PAGE_SIZE = 100


def render_agent_scores_chart(asset: str):
    """Graphique d'évolution des scores agents dans le temps pour un actif."""
    try:
        import plotly.graph_objects as go
        from storage.database import get_agent_scores_history
        import pandas as pd
    except ImportError:
        st.caption("plotly non disponible")
        return

    WINDOWS = [24, 48, 168, 720]
    WINDOW_LABELS = {24: "24h", 48: "48h", 168: "7j", 720: "30j"}
    COLORS = [
        "#7986cb", "#4fc3f7", "#81c784", "#ffb74d",
        "#f06292", "#ce93d8", "#80cbc4", "#fff176",
        "#ffcc80", "#a1c4fd",
    ]

    radio_key = f"agent_chart_win_{asset.replace('/', '_')}"
    hours = st.radio(
        "Fenêtre",
        WINDOWS,
        format_func=lambda h: WINDOW_LABELS[h],
        horizontal=True,
        key=radio_key,
        label_visibility="collapsed",
    )

    data = get_agent_scores_history(asset=asset, hours=hours)
    if not data:
        st.info(f"Pas encore d'historique ({WINDOW_LABELS[hours]}) pour {asset}.")
        return

    rows = []
    for entry in data:
        base = {
            "ts": entry["timestamp"],
            "action": entry.get("action", ""),
            "score_global": entry.get("global_score", 50),
            "market": entry.get("market_score", 50),
            "contrarian": entry.get("contrarian_score", 50),
            "mirofish": entry.get("mirofish_score", 50),
        }
        for ag, sc in entry.get("agent_scores", {}).items():
            base[ag] = sc
        rows.append(base)

    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.sort_values("ts").reset_index(drop=True)

    agent_cols = [c for c in df.columns if c not in ("ts", "action", "score_global")]

    fig = go.Figure()

    fig.add_hline(y=62, line_dash="dash", line_color="#2ecc71", line_width=1,
                  opacity=0.45, annotation_text="BUY≥62",
                  annotation_position="bottom right",
                  annotation_font=dict(size=9, color="#2ecc71"))
    fig.add_hline(y=52, line_dash="dash", line_color="#e74c3c", line_width=1,
                  opacity=0.45, annotation_text="EXIT<52",
                  annotation_position="bottom right",
                  annotation_font=dict(size=9, color="#e74c3c"))

    for i, col in enumerate(agent_cols):
        if col not in df.columns:
            continue
        fig.add_trace(go.Scatter(
            x=df["ts"], y=df[col],
            mode="lines", name=col,
            line=dict(color=COLORS[i % len(COLORS)], width=1.4),
            opacity=0.85,
            hovertemplate=f"{col}: %{{y:.0f}}<extra></extra>",
        ))

    # Score global en surimpression (blanc, plus épais)
    fig.add_trace(go.Scatter(
        x=df["ts"], y=df["score_global"],
        mode="lines", name="Global",
        line=dict(color="#ffffff", width=2.5),
        opacity=0.95,
        hovertemplate="Global: %{y:.1f}<extra></extra>",
    ))

    # Marqueurs BUY / SELL sur la ligne globale
    for action, sym, clr in [("BUY", "triangle-up", "#2ecc71"), ("SELL", "triangle-down", "#e74c3c")]:
        mask = df["action"] == action
        if mask.any():
            fig.add_trace(go.Scatter(
                x=df.loc[mask, "ts"], y=df.loc[mask, "score_global"],
                mode="markers", name=action,
                marker=dict(symbol=sym, size=11, color=clr,
                            line=dict(width=1, color="#000")),
                hovertemplate=f"{action}: %{{y:.1f}}<extra></extra>",
            ))

    from datetime import datetime, timezone, timedelta
    now_utc = datetime.now(timezone.utc)
    x_start_max = now_utc - timedelta(hours=hours)
    # df["ts"] est naive (UTC) — comparer en naive
    x_start_max_naive = now_utc.replace(tzinfo=None) - timedelta(hours=hours)
    x_start_naive = max(x_start_max_naive, df["ts"].min() - timedelta(minutes=15)) if len(df) else x_start_max_naive
    x_start = x_start_naive

    fig.update_layout(
        height=300,
        margin=dict(l=0, r=50, t=8, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.01,
                    xanchor="left", x=0, font=dict(size=9)),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(
            showgrid=False, tickfont=dict(size=10),
            range=[x_start, now_utc],
        ),
        yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.07)",
                   range=[0, 100], tickfont=dict(size=10)),
        font=dict(color="#c8c8c8"),
        hovermode="x unified",
    )

    st.markdown(
        '<p style="font-size:12px;font-weight:600;margin:4px 0 2px;">'
        '📈 Évolution des scores agents</p>',
        unsafe_allow_html=True,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False},
                    key=f"agent_scores_{asset.replace('/', '_')}_{hours}")


def render_live_logs(key: str = "global", asset: str | None = None):
    """Affiche les logs avec pagination (100 lignes par page). Si asset est fourni, filtre sur cet actif."""
    col_title, col_del = st.columns([5, 1])
    with col_title:
        st.markdown(
            f'<h3 style="margin:0 0 12px;font-size:18px;">'
            f'<i class="fas fa-terminal" style="margin-right:8px;color:#7986cb;"></i>'
            f'{t("logs_title")}</h3>',
            unsafe_allow_html=True,
        )
    with col_del:
        if st.button("🗑️ Vider", key=f"btn_clear_logs_{key}",
                     help="Supprime toutes les entrées de la table logs",
                     use_container_width=True):
            try:
                from storage.database import get_connection
                with get_connection() as conn:
                    conn.execute("DELETE FROM logs")
                    conn.commit()
                st.success("Logs supprimés.", icon="✅")
                st.rerun()
            except Exception as _e:
                st.error(f"Erreur suppression logs : {_e}")
    try:
        from storage.database import get_connection
        with get_connection() as conn:
            if asset:
                # Filtrer sur le symbole (ex: "BTC/USDT") et sa forme sans slash ("BTCUSDT")
                _slug = asset.replace("/", "")
                _pat1, _pat2 = f"%{asset}%", f"%{_slug}%"
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
                total_rows = conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
                all_rows = conn.execute(
                    "SELECT timestamp, level, module, message FROM logs "
                    "ORDER BY timestamp DESC"
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


def render_force_run_button():
    """Bouton pour forcer un cycle immédiatement."""
    if st.button("Force Run", type="primary", use_container_width=True,
                 help=t("force_run_help")):
        cfg = _get_settings()
        st.session_state["_force_run_asset"] = cfg.get("project", {}).get("asset", "BTC/USDT")


# ===========================================================
# COMPARAISON DES PROFILS SHADOW
# ===========================================================

def render_profile_comparison():
    """Section de comparaison des profils shadow vs baseline."""
    from comparison.shadow_runner import load_profiles

    profiles_cfg = load_profiles()
    if not profiles_cfg:
        return

    st.markdown(
        f'<h3 style="margin:0 0 12px;font-size:18px;">'
        f'<i class="fas fa-scale-balanced" style="margin-right:8px;color:#ff9800;"></i>'
        f'{t("profiles_title")}</h3>',
        unsafe_allow_html=True,
    )
    st.info(
        "⚠️ **Données héritées V1** — Le pipeline V2 (quant pur) ne génère plus de décisions "
        "par profil shadow. Les chiffres ci-dessous proviennent de l'ancien pipeline LLM et "
        "ne sont plus mis à jour. Utilisez **BO → Reset V2 → Vider profils shadow V1** pour purger.",
        icon="🗄️",
    )

    try:
        from storage.database import get_shadow_comparison_stats, get_shadow_pnl_series

        stats = get_shadow_comparison_stats()
        if not stats:
            st.info(t("profiles_no_data"))
            return

        # ── Tableau comparatif ──
        theme = _get_theme()
        if theme == "light":
            tbl_bg = "#ffffff"; tbl_fg = "#212529"
            head_bg = "#f1f3f5"; row_alt = "#f8f9fa"
            border = "#dee2e6"
        else:
            tbl_bg = "#161b22"; tbl_fg = "#e6edf3"
            head_bg = "#0d1117"; row_alt = "#1b2129"
            border = "rgba(255,255,255,0.08)"

        # Récupérer les couleurs des profils
        profile_colors = {}
        for name, cfg in profiles_cfg.items():
            profile_colors[name] = cfg.get("color", "#888")

        # Note méthodologique
        st.markdown(
            f'<p style="font-size:11px;color:#888;margin:0 0 10px;">'
            f'{t("profiles_shadow_note")}</p>',
            unsafe_allow_html=True,
        )

        cols = [t("col_profile"), t("profiles_trades"), t("profiles_winrate"),
                t("col_return_pct"), t("col_virtual_capital"), t("profiles_avg_pnl"), "Best", "Worst"]
        header = "".join(
            f'<th style="padding:8px 12px;text-align:{"left" if i == 0 else "right"};'
            f'background:{head_bg};font-weight:600;font-size:12px;'
            f'border-bottom:2px solid {border};">{c}</th>'
            for i, c in enumerate(cols)
        )

        rows_html = ""
        for idx, s in enumerate(stats):
            bg = row_alt if idx % 2 else tbl_bg
            color = profile_colors.get(s["profile"], "#888")
            label = s["profile"]
            for name, cfg in profiles_cfg.items():
                if name == s["profile"]:
                    _lk = f"profile_label_{name}"
                    _lt = t(_lk)
                    label = _lt if _lt != _lk else cfg.get("label", name)
                    break

            ret_pct = s.get("return_pct", 0)
            vcap = s.get("virtual_capital", 10000)
            avg_pnl = s.get("avg_pnl", 0)
            ret_color = "#00c853" if ret_pct >= 0 else "#ff1744"
            avg_color = "#00c853" if avg_pnl >= 0 else "#ff1744"
            wr_color = "#00c853" if s["win_rate"] >= 50 else ("#ff9800" if s["win_rate"] >= 40 else "#ff1744")
            # Capital virtuel : vert si au-dessus du capital initial, rouge si en dessous
            vcap_color = "#00c853" if vcap >= 10000 else "#ff1744"
            # Avertissement si trop peu d'échantillons
            sample_warn = ' <span style="color:#ff9800;font-size:10px;" title="< 5 évaluations — statistiquement peu fiable">⚠</span>' if s["evaluated"] < 5 and s["total_trades"] > 0 else ""

            rows_html += (
                f'<tr style="background:{bg};">'
                f'<td style="padding:6px 12px;font-weight:600;">'
                f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;'
                f'background:{color};margin-right:6px;"></span>{label}</td>'
                f'<td style="padding:6px 12px;text-align:right;">{s["total_trades"]}'
                f' <span style="color:#888;font-size:11px;">{t("profiles_evals").format(n=s["evaluated"])}</span>{sample_warn}</td>'
                f'<td style="padding:6px 12px;text-align:right;color:{wr_color};font-weight:600;">'
                f'{s["win_rate"]:.0f}%</td>'
                f'<td style="padding:6px 12px;text-align:right;color:{ret_color};font-weight:700;">'
                f'{ret_pct:+.2f}%</td>'
                f'<td style="padding:6px 12px;text-align:right;color:{vcap_color};">'
                f'${vcap:,.0f}</td>'
                f'<td style="padding:6px 12px;text-align:right;color:{avg_color};">'
                f'${avg_pnl:+.2f}</td>'
                f'<td style="padding:6px 12px;text-align:right;color:#00c853;">'
                f'${s["best_trade"]:+.2f}</td>'
                f'<td style="padding:6px 12px;text-align:right;color:#ff1744;">'
                f'${s["worst_trade"]:+.2f}</td>'
                f'</tr>'
            )

        st.markdown(
            f'<div style="border:1px solid {border};border-radius:8px;overflow:hidden;">'
            f'<table style="width:100%;border-collapse:collapse;color:{tbl_fg};font-size:13px;">'
            f'<thead><tr>{header}</tr></thead>'
            f'<tbody>{rows_html}</tbody></table></div>',
            unsafe_allow_html=True,
        )

        # ── Courbe rendement % cumulé (normalisée sur $10k initial) ──
        pnl_series = get_shadow_pnl_series()
        if pnl_series:
            st.markdown(
                f'<p style="margin:16px 0 8px;font-size:14px;font-weight:600;">'
                f'{t("profiles_cumulative")}</p>',
                unsafe_allow_html=True,
            )
            fig = go.Figure()
            for name, points in pnl_series.items():
                color = profile_colors.get(name, "#888")
                label = name
                for pname, cfg in profiles_cfg.items():
                    if pname == name:
                        _lk = f"profile_label_{pname}"
                        _lt = t(_lk)
                        label = _lt if _lt != _lk else cfg.get("label", pname)
                        break
                fig.add_trace(go.Scatter(
                    x=[p["timestamp"] for p in points],
                    y=[round(p["cumulative_pnl"] / 10000 * 100, 3) for p in points],
                    mode="lines+markers",
                    name=label,
                    line=dict(color=color, width=2),
                    marker=dict(size=4),
                    hovertemplate="%{y:+.2f}%<extra>" + label + "</extra>",
                ))
            fig.add_hline(y=0, line_dash="dash", line_color="rgba(255,255,255,0.2)", line_width=1)
            fig.update_layout(
                height=300,
                margin=dict(l=0, r=0, t=20, b=0),
                yaxis_title=t("chart_return_pct"),
                yaxis_tickformat="+.1f",
                legend=dict(orientation="h", y=-0.15),
                xaxis_title="",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color=tbl_fg, size=11),
            )
            st.plotly_chart(fig, use_container_width=True)

    except Exception as exc:
        st.caption(f"⚠️ Profils : {exc}")


# ===========================================================
# INTERFACE ADMIN
# ===========================================================

# render_admin_login() remplacé par dashboard.auth.render_auth(cm)


def render_admin_panel():
    """Panneau admin complet — configuration de tous les modules."""
    # Verrou: aucune UI d'auth ne doit se rendre pendant l'affichage admin.
    st.session_state["_suppress_auth_ui"] = True
    st.session_state.pop("_auth_step", None)
    st.session_state.pop("_auth_pending_user", None)
    st.session_state.pop("_auth_totp_new_secret", None)
    settings = _get_settings()
    if not settings:
        err = st.session_state.get("_settings_error", "fichier introuvable ou YAML invalide")
        st.error(f"{t('cfg_load_error')} — {err}")
        return

    # ── Navigation admin via sidebar custom ─────────────────────────────────
    from dashboard.multi_asset import _inject_custom_sidenav

    _ADMIN_SECTIONS = [
        # ── V4 — Moteur DAG ──────────────────────────────────────────────
        (None, None,      "V4 — Moteur DAG"),
        ('<i class="fas fa-diagram-project"></i>', "v4_canvas",  "Canvas DAG"),
        ('<i class="fas fa-chart-line"></i>',      "v4_monitor", "Monitoring V4"),
        ('<i class="fas fa-receipt"></i>',         "v4_trades",  "Trades V4"),
        ('<i class="fas fa-trophy"></i>',          "v4_arena",   "Arena"),
        ('<i class="fas fa-sliders"></i>',         "v4_admin",   "Config V4"),
        # ── Infra & Monitoring ───────────────────────────────────────────
        (None, None,      "Infra & Monitoring"),
        ('<i class="fas fa-robot"></i>',           "aimodel",    t("tab_ai_model")),
        ('<i class="fas fa-trash-alt"></i>',       "reset",      t("tab_reset_v2")),
        ('<i class="fas fa-list-check"></i>',      "logging",    t("tab_logging")),
        ('<i class="fas fa-history"></i>',         "historique",  "Historique"),
        ('<i class="fas fa-user"></i>',            "users",      t("tab_users")),
        ('<i class="fas fa-floppy-disk"></i>',     "backup",     t("tab_backup")),
    ]
    _admin_keys = [s[1] for s in _ADMIN_SECTIONS if s[1] is not None]
    _admin_items = [
        {"section": s[2]} if s[1] is None
        else {"key": s[1], "icon": s[0], "text": s[2]}
        for s in _ADMIN_SECTIONS
    ]
    _atab = st.query_params.get("_atab", "v4_canvas")
    if _atab not in _admin_keys:
        _atab = "v4_canvas"
    _inject_custom_sidenav(_admin_items, _atab, qparam="_atab", theme=_get_theme())

    if _atab == "quant":  # Quant V2 Pipeline
        st.markdown(
            f'<h4><i class="fas fa-microchip" style="margin-right:7px;color:#7986cb;"></i>'
            f'{t("tab_quant_v2")}</h4>',
            unsafe_allow_html=True,
        )
        st.info(t("quant_info"))
        q = settings.get("quant", {})
        col1, col2 = st.columns(2)
        with col1:
            _tf_opts = ["1m", "5m", "15m", "30m", "1h", "4h"]
            _tf_cur = q.get("timeframe", "5m")
            if _tf_cur not in _tf_opts:
                _tf_opts.append(_tf_cur)
            q["timeframe"] = st.selectbox(
                t("quant_timeframe"), _tf_opts,
                index=_tf_opts.index(_tf_cur),
                help="Granularité des barres OHLCV (ccxt notation).",
            )
            if q["timeframe"] != _tf_cur:
                st.info(t("quant_tf_change_warn"))
            q["history_days"] = st.slider(
                t("quant_history_days"), 30, 365,
                int(q.get("history_days", 90)), 10,
                help="Nombre de jours d'historique chargés au refit.",
            )
            q["train_fraction"] = st.slider(
                t("quant_train_fraction"), 0.55, 0.85,
                float(q.get("train_fraction", 0.70)), 0.05,
                help="Fraction des données utilisées pour l'entraînement.",
            )
            _hz_options = [1, 2, 4, 8, 12, 16, 24, 32, 48, 96]
            _hz_val = int(q.get("horizon_bars", 4))
            _hz_idx = _hz_options.index(_hz_val) if _hz_val in _hz_options else 0
            q["horizon_bars"] = st.selectbox(
                t("quant_horizon_bars"), _hz_options,
                index=_hz_idx,
                help="Horizon de prédiction en barres (ex: 12 × 5min = 1h avec TF 5m).",
            )
        with col2:
            q["p_up_threshold"] = st.slider(
                t("quant_p_up_label"), 0.50, 0.75,
                float(q.get("p_up_threshold", 0.55)), 0.01,
                help="Au-dessus de ce seuil en régime trending → signal LONG.",
            )
            q["p_dn_threshold"] = st.slider(
                t("quant_p_dn_label"), 0.25, 0.50,
                float(q.get("p_dn_threshold", 0.45)), 0.01,
                help="En dessous de ce seuil en régime trending → signal SHORT.",
            )
            _dead_zone = q["p_up_threshold"] - q["p_dn_threshold"]
            st.caption(t("quant_dead_zone").format(dn=q['p_dn_threshold'], up=q['p_up_threshold'], amp=_dead_zone))
            q["refit_interval_hours"] = st.number_input(
                t("quant_refit_interval"), 12, 720,
                int(q.get("refit_interval_hours", 168)), 12,
                help="Le modèle est réentraîné automatiquement toutes les N heures.",
            )
            q["use_hmm"] = st.toggle(
                t("quant_use_hmm"),
                bool(q.get("use_hmm", False)),
                help="Active le filtre HMM (hmmlearn requis — désactiver en local si absent).",
            )
        settings["quant"] = q

        # ── Sources de données (TwelveData) ──────────────────────────────────
        st.markdown("---")
        st.markdown(f"#### {t('quant_section_sources')}")
        _dp_opts = ["auto", "twelve_data", "yahoo"]
        _dp_cur = q.get("data_provider", settings.get("data", {}).get("provider", "auto"))
        if _dp_cur not in _dp_opts:
            _dp_cur = "auto"
        _dp_new = st.selectbox(
            t("quant_data_provider"),
            _dp_opts,
            index=_dp_opts.index(_dp_cur),
            help="**auto** : essaie Twelve Data (si clé présente) puis Yahoo/Binance. "
                 "**twelve_data** : force Twelve Data pour les actifs forex/commodités. "
                 "**yahoo** : force Yahoo Finance.",
        )
        settings["quant"]["data_provider"] = _dp_new
        settings.setdefault("data", {})["provider"] = _dp_new

        # Lecture de la clé TwelveData (secrets.yaml en priorité)
        try:
            from quant.config import get_twelve_data_key as _get_td_key
            _td_key_live = _get_td_key()
        except Exception:
            _td_key_live = ""
        _td_key_display = ("*" * 8 + _td_key_live[-4:]) if len(_td_key_live) > 4 else ("(vide)" if not _td_key_live else _td_key_live)
        st.caption(f"Clé TwelveData active : `{_td_key_display}`")
        _td_key_input = st.text_input(
            t("quant_td_key_new"),
            value="",
            type="password",
            help="La clé sera écrite dans **config/secrets.yaml** (gitignored). "
                 "Laissez vide pour conserver la clé actuelle.",
        )
        if _td_key_input.strip():
            from pathlib import Path as _SPPath
            import yaml as _syaml
            _secrets_path = _SPPath(__file__).resolve().parent.parent / "config" / "secrets.yaml"
            try:
                _sec = _syaml.safe_load(_secrets_path.read_text(encoding="utf-8")) or {} if _secrets_path.exists() else {}
                _sec.setdefault("data", {})["twelve_data_key"] = _td_key_input.strip()
                _secrets_path.write_text(_syaml.dump(_sec, allow_unicode=True), encoding="utf-8")
                st.success(t("quant_td_key_saved"))
            except Exception as _se:
                st.error(f"Erreur écriture secrets.yaml : {_se}")

        # ── État live du modèle ───────────────────────────────────────────────
        st.markdown("---")
        st.markdown(f"#### {t('quant_model_state_title')}")
        try:
            from storage.database import get_v2_state
            _qs = get_v2_state()
            if _qs:
                _qa, _qb = st.columns(2)
                _qa.metric(t("quant_last_refit"), str(_qs.get("model_fit_at", "—"))[:16])
                _qa.metric(t("quant_current_regime"), "TRENDING" if _qs.get("regime") in (1, 1.0) else ("RANGING" if _qs.get("regime") == 0.5 else "PANIC"))
                _qb.metric("P(up)", f"{_qs.get('prob_up', 0):.1%}" if _qs.get("prob_up") else "—")
                _qb.metric(t("quant_decision"), str(_qs.get("action", "—")).upper())
            else:
                st.info(t("quant_no_cycle"))
        except Exception as _qe:
            st.caption(f"État indisponible : {_qe}")

    elif _atab == "risk":  # Risk
        st.markdown(f'<h4><i class="fas fa-shield-halved" style="margin-right:7px;color:#7986cb;"></i>{t("cfg_risk_title")}</h4>', unsafe_allow_html=True)

        st.info(t("cfg_risk_info"))
        st.caption(t("cfg_risk_peractif_hint"))
        risk = settings.get("risk", {})
        risk["human_in_the_loop"] = st.toggle(
            t("cfg_hitl"),
            risk.get("human_in_the_loop", False),
            help=t("cfg_hitl_help")
        )
        risk["max_open_positions"] = st.number_input(
            t("cfg_max_open_pos"),
            min_value=0, max_value=20,
            value=int(risk.get("max_open_positions", 3)),
            help="Nombre maximum de positions simultanées **toutes paires confondues**."
        )
        settings["risk"] = risk

        st.markdown("---")
        st.markdown(f'<h4><i class="fas fa-exchange-alt" style="margin-right:7px;color:#ef9a9a;"></i>{t("cfg_exchange_title")}</h4>', unsafe_allow_html=True)
        st.info(t("cfg_exchange_info"))
        exch = settings.get("exchange", {})
        st.caption(t("cfg_exchange_peractif_hint"))
        _testnet_current = exch.get("testnet", True)
        _testnet_new = st.toggle(t("cfg_testnet"), value=_testnet_current)
        exch["testnet"] = _testnet_new
        if not _testnet_new:
            st.error(t("cfg_testnet_warn"))
        settings["exchange"] = exch

    elif _atab == "logging":  # Logging
        st.markdown(f'<h4><i class="fas fa-list-check" style="margin-right:7px;color:#7986cb;"></i>{t("cfg_logging_title")}</h4>', unsafe_allow_html=True)
        st.info(t("cfg_logging_info"))
        log_cfg = settings.get("logging", {})
        _log_levels = ["DEBUG", "INFO", "WARNING", "ERROR"]
        _log_default = log_cfg.get("level", "INFO")
        if _log_default not in _log_levels:
            _log_levels.append(_log_default)
        log_cfg["level"] = st.radio(t("cfg_log_level"), _log_levels,
            index=_log_levels.index(_log_default),
            horizontal=True, help=t("cfg_log_level_help"))
        log_cfg["alert_score_threshold"] = st.slider(t("cfg_alert_threshold"),
            50, 100, int(log_cfg.get("alert_score_threshold", 85)),
            help=t("cfg_alert_threshold_help"))
        log_cfg["telegram_enabled"] = st.toggle("Telegram", log_cfg.get("telegram_enabled", False))
        log_cfg["discord_enabled"] = st.toggle("Discord", log_cfg.get("discord_enabled", False))
        settings["logging"] = log_cfg

    elif _atab == "aimodel":  # Modèle IA
        st.markdown(
            '<h4><i class="fas fa-robot" style="margin-right:7px;color:#7986cb;"></i>'
            f'{t("tab_ai_model")}</h4>',
            unsafe_allow_html=True,
        )
        st.info(t("ai_model_info"))

        _llm = dict(settings.get("llm", {}))

        _providers = ["deepseek", "openai", "anthropic", "groq", "mistral", "ollama"]
        _provider_models = {
            "deepseek":  ["deepseek-v4-pro", "deepseek-v4-flash", "deepseek-chat", "deepseek-reasoner"],
            "openai":    ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
            "anthropic": ["claude-3-5-haiku-20241022", "claude-3-5-sonnet-20241022", "claude-opus-4-5"],
            "groq":      ["llama-3.3-70b-versatile", "mixtral-8x7b-32768"],
            "mistral":   ["mistral-small-latest", "mistral-medium-latest", "mistral-large-latest"],
            "ollama":    ["llama3", "mistral", "phi3"],
        }
        _key_field = {
            "deepseek":  "deepseek_api_key",
            "openai":    "openai_api_key",
            "anthropic": "anthropic_api_key",
            "groq":      "groq_api_key",
            "mistral":   "mistral_api_key",
            "ollama":    None,
        }

        _cur_provider = _llm.get("provider", "deepseek")
        if _cur_provider not in _providers:
            _providers.append(_cur_provider)

        _c1, _c2 = st.columns(2)
        with _c1:
            _new_provider = st.selectbox(
                t("ai_provider"), _providers,
                index=_providers.index(_cur_provider),
                key="ai_provider_sel",
            )
        _model_opts = _provider_models.get(_new_provider, [_llm.get("model", "")])
        _cur_model = _llm.get("model", _model_opts[0] if _model_opts else "")
        if _cur_model not in _model_opts:
            _model_opts = [_cur_model] + _model_opts
        with _c2:
            _new_model = st.selectbox(
                t("ai_model"), _model_opts,
                index=_model_opts.index(_cur_model),
                key="ai_model_sel",
            )

        # Clé API — affichée seulement si le provider en a besoin
        _key_name = _key_field.get(_new_provider)
        _existing_key = _llm.get(_key_name, "") if _key_name else ""
        _new_key = _existing_key
        if _key_name:
            _new_key = st.text_input(
                t("ai_api_key"),
                value="",
                placeholder="Laisser vide pour conserver la clé actuelle",
                type="password",
                key="ai_api_key_input",
                help=t("ai_api_key_help"),
            )
            if _existing_key:
                _masked = "sk-" + "*" * (len(_existing_key) - 7) + _existing_key[-4:]
                st.caption(f"🔑 Clé actuelle : `{_masked}`")
            else:
                st.caption("⚠️ Aucune clé API configurée.")
            # Si l'utilisateur laisse vide → conserver l'ancienne clé
            if not _new_key:
                _new_key = _existing_key
        else:
            st.caption(f"ℹ️ {_new_provider} — pas de clé API requise (local).")

        _c3, _c4 = st.columns(2)
        with _c3:
            _llm["temperature"] = st.slider(
                t("ai_temperature"), 0.0, 1.0,
                float(_llm.get("temperature", 0.3)), 0.05,
                key="ai_temp_sl",
            )
        with _c4:
            _llm["max_tokens"] = st.number_input(
                t("ai_max_tokens"), 256, 32000,
                int(_llm.get("max_tokens", 4096)), 256,
                key="ai_maxtok_ni",
            )

        _llm["provider"] = _new_provider
        _llm["model"]    = _new_model
        if _key_name and _new_key:
            _llm[_key_name] = _new_key
        settings["llm"] = _llm

    elif _atab == "flux":  # Flux Manager
        st.markdown('<h4><i class="fas fa-exchange-alt" style="margin-right:7px;color:#7986cb;"></i> Flux Manager</h4>', unsafe_allow_html=True)
        st.info(t("cfg_flux_info"))
        render_flux_manager_page()
        # pas de bouton save ici, géré dans flux_manager

    elif _atab == "users":  # Utilisateurs
        st.markdown('<h4><i class="fas fa-user" style="margin-right:7px;color:#7986cb;"></i> Utilisateurs</h4>', unsafe_allow_html=True)
        st.info(t("cfg_users_info"))
        from dashboard.auth import render_users_admin
        render_users_admin()
        # sauvegarde gérée dans render_users_admin

    elif _atab == "peractif":  # Par Actif — config/assets/{slug}.yaml
        st.markdown(
            '<h4><i class="fas fa-layer-group" style="margin-right:7px;color:#7986cb;"></i>'
            f'{t("pa_title")}</h4>',
            unsafe_allow_html=True,
        )
        st.info(t("pa_info"))

        # ── Actifs — liste combinée intraday + daily (lecture seule ici) ────────
        st.caption("📋 Pour ajouter ou retirer des actifs, utilisez l'onglet **Flux Manager**.")
        _pa_intraday = list(settings.get("project", {}).get("active_assets", ["BTC/USDT"]))
        _pa_daily = list(
            settings.get("project", {}).get("daily_active_assets")
            or settings.get("quant", {}).get("daily_active_assets")
            or []
        )
        _pa_all = list(dict.fromkeys(_pa_intraday + _pa_daily))

        st.markdown("---")
        import yaml as _pa_yaml
        from pathlib import Path as _PAPath
        from dashboard.multi_asset import _asset_icon as _pa_icon
        _pa_tabs = st.tabs([f"{_pa_icon(a)} {a.split('/')[0]}" for a in _pa_all])
        _padir = _PAPath(__file__).parent.parent / "config" / "assets"

        for _pai, _pas in enumerate(_pa_all):
            with _pa_tabs[_pai]:
                _paslug = _pas.replace("/", "_")
                _pafile = _padir / f"{_paslug}.yaml"
                _pacfg: dict = {}
                if _pafile.exists():
                    with open(_pafile, "r", encoding="utf-8") as _paf:
                        _pacfg = _pa_yaml.safe_load(_paf) or {}
                _is_crypto_pa = _pas.endswith("/USDT") or _pas.endswith("/BTC")
                _is_forex_pa  = any(_pas.endswith(s) for s in ("/USD", "/EUR", "/GBP", "/JPY")) and not _is_crypto_pa
                _is_commodity_pa = _pas in ("XAU/USD", "XAG/USD", "WTI/USD")

                st.caption(
                    "💡 V2 lit les paramètres globaux (settings.yaml). "
                    "Ces valeurs seront utilisées comme surcharges par actif dans une version future."
                )

                # ── Général ──────────────────────────────────────────────────
                with st.expander("⚙ Général", expanded=True):
                    _c1, _c2 = st.columns(2)
                    with _c1:
                        _pacfg["paper_capital_usd"] = st.number_input(
                            "Capital paper (USD)", 1000, 1_000_000,
                            int(_pacfg.get("paper_capital_usd", 10000)), step=500,
                            key=f"pa_cap_{_paslug}"
                        )
                    with _c2:
                        _pacfg["loop_interval_seconds"] = st.number_input(
                            "Intervalle boucle (s)", 60, 3600,
                            int(_pacfg.get("loop_interval_seconds", 900)), step=60,
                            key=f"pa_loop_{_paslug}"
                        )

                # ── Risk & Seuils (V3 — source of truth: v2_risk) ───────────────────────
                with st.expander("⚖ Risk & Seuils", expanded=True):
                    _v2r = dict(_pacfg.get("v2_risk", {}))
                    _par_extra = dict(_pacfg.get("risk", {}))  # human_in_the_loop + max_open_positions
                    _c1, _c2 = st.columns(2)
                    with _c1:
                        _new_frac = st.slider(
                            "Position size (%)", 0.1, 5.0,
                            round(float(_v2r.get("fraction_per_trade", 0.0075)) * 100, 3), 0.05,
                            key=f"pa_pos_{_paslug}",
                            help="fraction_per_trade × 100 — written to v2_risk (read by graph/workflow.py)"
                        )
                        _new_dd = st.slider(
                            t("pa_max_dd"), 3.0, 50.0,
                            float(_v2r.get("max_drawdown_pct", 15.0)), 1.0,
                            key=f"pa_dd_{_paslug}"
                        )
                        _new_mop = st.number_input(
                            t("pa_max_positions"), 0, 20,
                            int(_par_extra.get("max_open_positions", 3)),
                            key=f"pa_mop_{_paslug}",
                            help="0 = unlimited."
                        )
                    with _c2:
                        _new_sl = st.slider(
                            "ATR ×SL", 0.5, 5.0,
                            float(_v2r.get("stop_loss_atr_mult", 2.0)), 0.25,
                            key=f"pa_atrs_{_paslug}",
                            help="stop_loss_atr_mult — written to v2_risk"
                        )
                        _new_tp = st.slider(
                            "ATR ×TP", 0.5, 8.0,
                            float(_v2r.get("take_profit_atr_mult", 4.0)), 0.25,
                            key=f"pa_atrtp_{_paslug}",
                            help="take_profit_atr_mult — written to v2_risk"
                        )
                        _new_hitl = st.toggle(
                            "Human in the loop",
                            _par_extra.get("human_in_the_loop", False),
                            key=f"pa_hitl_{_paslug}"
                        )
                    # Write back to v2_risk (used by graph/workflow.py V3 engine)
                    _pacfg["v2_risk"] = {
                        **_v2r,
                        "fraction_per_trade": round(_new_frac / 100, 6),
                        "stop_loss_atr_mult": _new_sl,
                        "take_profit_atr_mult": _new_tp,
                        "max_drawdown_pct": _new_dd,
                    }
                    _pacfg["risk"] = {
                        **_par_extra,
                        "human_in_the_loop": _new_hitl,
                        "max_open_positions": int(_new_mop),
                    }

                # ── Circuit Breaker (crypto uniquement) ──────────────────────
                if _is_crypto_pa:
                    with st.expander("⚡ Circuit Breaker (Funding Rate)", expanded=False):
                        _pcb = dict(_pacfg.get("circuit_breaker", {}))
                        _c1, _c2 = st.columns(2)
                        with _c1:
                            _pcb["funding_warning"] = st.number_input(
                                "Warning threshold", 0.0, 0.01,
                                float(_pcb.get("funding_warning", 0.00018)),
                                format="%.5f", key=f"pa_cbw_{_paslug}"
                            )
                            _pcb["funding_block"] = st.number_input(
                                "Block threshold", 0.0, 0.01,
                                float(_pcb.get("funding_block", 0.00045)),
                                format="%.5f", key=f"pa_cbb_{_paslug}"
                            )
                        with _c2:
                            _pcb["sustain_period_cycles"] = st.number_input(
                                "Sustain cycles", 0, 10,
                                int(_pcb.get("sustain_period_cycles", 3)),
                                key=f"pa_cbsc_{_paslug}"
                            )
                            _pcb["max_reduction"] = st.slider(
                                t("pa_cb_max_reduction"), 0.0, 1.0,
                                float(_pcb.get("max_reduction", 0.75)), 0.05,
                                key=f"pa_cbmr_{_paslug}"
                            )
                        _pacfg["circuit_breaker"] = _pcb

                # ── Market Regime (V2) ────────────────────────────────────────
                with st.expander("⊞ Market Regime", expanded=False):
                    _pmr = dict(_pacfg.get("market_regime", {}))
                    _c1, _c2 = st.columns(2)
                    with _c1:
                        _pmr["n_hmm_states"] = st.number_input(
                            t("pa_hmm_states"), 2, 4, int(_pmr.get("n_hmm_states", 2)),
                            key=f"pa_hmm_{_paslug}"
                        )
                        _pmr["adx_period"] = st.slider(
                            t("pa_adx_period"), 7, 30, int(_pmr.get("adx_period", 18)),
                            key=f"pa_adx_{_paslug}"
                        )
                    with _c2:
                        _pmr["vol_window"] = st.slider(
                            t("pa_vol_window"), 10, 60, int(_pmr.get("vol_window", 30)),
                            key=f"pa_vw_{_paslug}"
                        )
                        _pmr["trend_window"] = st.slider(
                            t("pa_trend_window"), 20, 100, int(_pmr.get("trend_window", 50)),
                            key=f"pa_tw_{_paslug}"
                        )
                    _pacfg["market_regime"] = _pmr

                # ── Bouton Sauvegarder ────────────────────────────────────────
                st.markdown("---")
                if st.button(
                    t("pa_save_btn").format(asset=_pas),
                    key=f"pa_save_{_paslug}",
                    type="primary",
                    use_container_width=True,
                ):
                    try:
                        from utils.config import save_asset_config as _sac
                        _padir.mkdir(parents=True, exist_ok=True)
                        _sac(_pas, _pacfg)
                        st.success(t("pa_save_success").format(slug=_paslug))
                    except Exception as _savexc:
                        st.error(f"{t('pa_save_error')} {_savexc}")

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
                for _bk in _backups[:10]:  # max 10 affichées
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
                        if st.button("🔄", key=f"restore_{_bk['filename']}", help="Restaurer cette sauvegarde"):
                            try:
                                _r = import_config_zip(_bk_bytes, backup_first=True)
                                st.success(t("bkp_restore_from").format(n=len(_r['restored_files']), filename=_bk['filename']))
                            except Exception as _re:
                                st.error(f"❌ {_re}")
        except Exception as _lb_exc:
            st.caption(f"{t('bkp_list_error')} {_lb_exc}")

    elif _atab == "reset":  # Purge des données
        st.markdown(
            f'<h4><i class="fas fa-trash-alt" style="margin-right:7px;color:#e74c3c;"></i>'
            f' {t("reset_page_title")}</h4>',
            unsafe_allow_html=True,
        )
        st.warning(t("reset_warning"))

        # ── Reset partiel ─────────────────────────────────────────────────
        st.markdown(f"#### {t('reset_partial_title')}")
        st.caption(t("reset_partial_caption"))
        _col_r3, _col_r4 = st.columns(2)
        with _col_r3:
            if st.button(t("reset_partial_btn"), type="secondary", use_container_width=True, key="reset_v2_partial"):
                try:
                    import sqlite3 as _sq3
                    from utils.config import load_settings as _ls_r
                    _db_r = _ls_r().get("logging", {}).get("sqlite_db", "storage/zeitgeist.db")
                    with _sq3.connect(_db_r) as _con_r:
                        _con_r.execute("DELETE FROM v2_equity")
                        _con_r.execute("DELETE FROM v2_state")
                        _con_r.commit()
                    st.success(t("reset_partial_ok"))
                except Exception as _re_r:
                    st.error(f"Erreur : {_re_r}")
        with _col_r4:
            st.caption(t("reset_partial_warn"))

        # ── Reset complet ─────────────────────────────────────────────────
        st.markdown("---")
        st.markdown(f"#### {t('reset_full_title')}")
        st.caption(t("reset_full_caption"))
        _confirm_full = st.checkbox(t("reset_full_confirm"), key="confirm_full_reset")
        _col_r7, _col_r8 = st.columns(2)
        with _col_r7:
            if st.button(t("reset_full_btn"), type="primary",
                         use_container_width=True, key="reset_v2_full",
                         disabled=not _confirm_full):
                import subprocess as _sp2
                import sqlite3 as _sq3b
                _ok_db = False
                try:
                    from utils.config import load_settings as _ls_r2
                    _db_r2 = _ls_r2().get("logging", {}).get("sqlite_db", "storage/zeitgeist.db")
                    with _sq3b.connect(_db_r2) as _con_r2:
                        _con_r2.execute("DELETE FROM v2_equity")
                        _con_r2.execute("DELETE FROM v2_state")
                        _con_r2.execute("DELETE FROM v2_decisions")
                        _con_r2.commit()
                    st.success(t("reset_full_ok"))
                    _ok_db = True
                except Exception as _re_r2:
                    st.error(f"Erreur DB : {_re_r2}")
                if _ok_db:
                    try:
                        _res2 = _sp2.run(
                            ["supervisorctl", "-s", "unix:///tmp/supervisor.sock", "restart", "trader"],
                            capture_output=True, text=True, timeout=15,
                        )
                        if _res2.returncode == 0:
                            st.success(t("reset_daemon_ok2"))
                        else:
                            st.warning(f"DB purgée mais redémarrage échoué (rc={_res2.returncode}) : {_res2.stderr or _res2.stdout}")
                    except Exception as _re_ex2:
                        st.warning(f"DB purgée mais redémarrage échoué : {_re_ex2}")
        with _col_r8:
            st.caption(t("reset_full_caption"))

        # ── Redémarrage seul ──────────────────────────────────────────────
        st.markdown("---")
        st.markdown(f"#### {t('reset_daemon_title')}")
        _col_r5, _col_r6 = st.columns(2)
        with _col_r5:
            if st.button(t("reset_daemon_btn"), type="secondary", use_container_width=True, key="restart_trader"):
                import subprocess as _sp
                try:
                    _res = _sp.run(
                        ["supervisorctl", "-s", "unix:///tmp/supervisor.sock", "restart", "trader"],
                        capture_output=True, text=True, timeout=15,
                    )
                    if _res.returncode == 0:
                        st.success(t("reset_daemon_ok"))
                    else:
                        st.error(f"Erreur supervisorctl (rc={_res.returncode}) : {_res.stderr or _res.stdout}")
                except FileNotFoundError:
                    st.error(t("reset_err_supervisorctl"))
                except Exception as _re_ex:
                    st.error(f"Erreur : {_re_ex}")
        with _col_r6:
            st.caption(t("reset_daemon_caption"))

    elif _atab == "historique":  # Historique des décisions V2
        st.markdown(
            '<h4><i class="fas fa-history" style="margin-right:7px;color:#9c27b0;"></i>'
            ' Historique des Décisions V2</h4>',
            unsafe_allow_html=True,
        )
        try:
            from storage.database import get_connection as _hget_conn
            _h_col1, _h_col2, _h_col3, _h_col4 = st.columns([2, 1, 1, 1])
            try:
                from utils.config import get_active_assets as _h_get_all
                _h_assets_raw = _h_get_all()
            except Exception:
                _h_assets_raw = settings.get("project", {}).get("active_assets", [])
            _h_assets_list = ["Tous"] + (list(_h_assets_raw) if _h_assets_raw else ["BTC/USDT"])
            with _h_col1:
                _h_asset = st.selectbox("Actif", _h_assets_list, key="hist_asset")
            with _h_col2:
                _h_action = st.selectbox("Action", ["Toutes", "long", "short", "flat"], key="hist_action")
            with _h_col3:
                _h_regime = st.selectbox("Régime", ["Tous", "TREND", "RANGE", "PANIC"], key="hist_regime")
            with _h_col4:
                _h_n = int(st.number_input("Lignes max", 50, 5000, 500, 50, key="hist_n"))

            _h_where, _h_params = [], []
            if _h_asset != "Tous":
                _h_where.append("asset = ?"); _h_params.append(_h_asset)
            if _h_action != "Toutes":
                _h_where.append("action = ?"); _h_params.append(_h_action)
            if _h_regime != "Tous":
                _h_where.append("regime = ?"); _h_params.append(_h_regime)
            _h_where_sql = ("WHERE " + " AND ".join(_h_where)) if _h_where else ""

            with _hget_conn() as _hconn:
                _tbl_exists = _hconn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='v2_decisions'"
                ).fetchone()
                if not _tbl_exists:
                    st.info("📊 La table d'historique sera créée automatiquement au prochain cycle du trader.")
                else:
                    _h_stats = _hconn.execute(
                        f"""SELECT COUNT(*) as total,
                               SUM(CASE WHEN action='long'  THEN 1 ELSE 0 END) as n_long,
                               SUM(CASE WHEN action='short' THEN 1 ELSE 0 END) as n_short,
                               SUM(CASE WHEN action='flat'  THEN 1 ELSE 0 END) as n_flat,
                               SUM(CASE WHEN regime='TREND' THEN 1 ELSE 0 END) as n_trend,
                               SUM(CASE WHEN regime='RANGE' THEN 1 ELSE 0 END) as n_range,
                               SUM(CASE WHEN regime='PANIC' THEN 1 ELSE 0 END) as n_panic
                           FROM v2_decisions {_h_where_sql}""",
                        _h_params,
                    ).fetchone()
                    if _h_stats and _h_stats[0] > 0:
                        _h_total = _h_stats[0]
                        _hc1, _hc2, _hc3, _hc4, _hc5, _hc6, _hc7 = st.columns(7)
                        _hc1.metric("Total cycles", _h_total)
                        _hc2.metric("LONG",  f"{_h_stats[1]} ({_h_stats[1]/_h_total*100:.0f}%)")
                        _hc3.metric("SHORT", f"{_h_stats[2]} ({_h_stats[2]/_h_total*100:.0f}%)")
                        _hc4.metric("FLAT",  f"{_h_stats[3]} ({_h_stats[3]/_h_total*100:.0f}%)")
                        _hc5.metric("TREND", f"{_h_stats[4]} ({_h_stats[4]/_h_total*100:.0f}%)")
                        _hc6.metric("RANGE", f"{_h_stats[5]} ({_h_stats[5]/_h_total*100:.0f}%)")
                        _hc7.metric("PANIC", f"{_h_stats[6]} ({_h_stats[6]/_h_total*100:.0f}%)")
                        st.markdown("---")
                        _h_rows = _hconn.execute(
                            f"""SELECT ts, asset, bar_ts, close_price, regime, prob_up,
                                       action, reason, atr_14, sl_price, tp_price, capital
                                FROM v2_decisions {_h_where_sql}
                                ORDER BY ts DESC LIMIT ?""",
                            _h_params + [_h_n],
                        ).fetchall()
                        import pandas as _hpd
                        _h_df = _hpd.DataFrame(
                            _h_rows,
                            columns=["Horodatage", "Actif", "Barre", "Prix", "Régime",
                                     "P(up)", "Action", "Raison", "ATR", "SL", "TP", "Capital"],
                        )
                        _h_df["Horodatage"] = _h_df["Horodatage"].apply(lambda x: x[:19] if x else "")
                        _h_df["Barre"]      = _h_df["Barre"].apply(lambda x: x[:16] if x else "")
                        _h_df["P(up)"]      = _h_df["P(up)"].apply(lambda x: f"{x:.3f}" if x is not None else "N/A")
                        _h_df["Prix"]       = _h_df["Prix"].apply(lambda x: f"{x:.4f}" if x else "—")
                        _h_df["ATR"]        = _h_df["ATR"].apply(lambda x: f"{x:.6f}" if x else "—")
                        _h_df["SL"]         = _h_df["SL"].apply(lambda x: f"{x:.4f}" if x else "—")
                        _h_df["TP"]         = _h_df["TP"].apply(lambda x: f"{x:.4f}" if x else "—")
                        _h_df["Capital"]    = _h_df["Capital"].apply(lambda x: f"{x:.2f}$" if x else "—")
                        st.dataframe(_h_df, use_container_width=True, hide_index=True)
                        # Export CSV
                        _h_csv = _h_df.to_csv(index=False).encode("utf-8")
                        st.download_button(
                            "⬇️ Exporter CSV",
                            _h_csv,
                            file_name="v2_decisions.csv",
                            mime="text/csv",
                            key="hist_dl_csv",
                        )
                    else:
                        st.info("Aucune décision enregistrée avec ces filtres.")
        except Exception as _he:
            st.error(f"Erreur lecture historique : {_he}")

    # Bouton de sauvegarde (pour tous les onglets sauf Flux Manager, Par Actif, Sauvegarde, Reset et Historique)
    if _atab not in ("backup", "flux", "peractif", "reset", "historique"):
        st.markdown("---")
    if _atab == "backup":
        pass  # pas de bouton save_settings pour l'onglet backup
    elif _atab == "reset":
        pass  # le panneau reset gère ses propres boutons
    elif _atab == "historique":
        pass  # le panneau historique gère son propre affichage
    elif _atab in ("v4_canvas", "v4_monitor", "v4_trades", "v4_arena", "v4_admin"):
        _V4_URLS = {
            "v4_canvas":  "http://localhost:3000/canvas",
            "v4_monitor": "http://localhost:3000/monitoring",
            "v4_trades":  "http://localhost:3000/trades",
            "v4_arena":   "http://localhost:3000/arena",
            "v4_admin":   "http://localhost:3000/admin",
        }
        _V4_LABELS = {
            "v4_canvas":  "Canvas DAG",
            "v4_monitor": "Monitoring V4",
            "v4_trades":  "Trades V4",
            "v4_arena":   "Arena",
            "v4_admin":   "Config V4",
        }
        _v4_url = _V4_URLS[_atab]
        _v4_label = _V4_LABELS[_atab]
        st.markdown(
            f'<h4 style="margin-bottom:12px;">'
            f'<i class="fas fa-diagram-project" style="margin-right:8px;color:#4f6ef7;"></i>'
            f'{_v4_label}</h4>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<iframe src="{_v4_url}" '
            f'style="width:100%;height:calc(100vh - 120px);border:none;border-radius:8px;'
            f'background:#0f1117;" '
            f'allow="clipboard-read;clipboard-write" allowfullscreen></iframe>',
            unsafe_allow_html=True,
        )
    elif st.button(t('save_config_btn'), type="primary", use_container_width=True):
        if _save_settings(settings):
            st.success(f"✅ {t('config_saved')}")
        else:
            _err = st.session_state.pop("_save_error", "inconnue")
            st.error(f"❌ {t('config_error')} — {_err}")


# ===========================================================
# SESSION PERSISTENCE (localStorage)
# ===========================================================

def _inject_sticky_tabs_js() -> None:
    """
    Sticky tabs — injecte CSS dans <head> (permanent) + JS MutationObserver
    pour corriger l'overflow:hidden inline sur le parent direct du tab-list
    (généré par Streamlit React, inaccessible via CSS pur).
    """
    import streamlit.components.v1 as _cv1
    _cv1.html("""<script>
(function() {
  var p = window.parent || window;
  var doc = p.document;

  // 1. CSS dans <head> — permanent, survit aux re-renders Streamlit
  if (!doc.getElementById('atlas-sticky-tabs-css')) {
    var s = doc.createElement('style');
    s.id = 'atlas-sticky-tabs-css';
    s.textContent =
      'div[data-baseweb="tab-list"] {' +
      '  position: sticky !important;' +
      '  top: 48px !important;' +
      '  z-index: 998 !important;' +
      '}';
    doc.head.appendChild(s);
  }

  // 2. Correction des overflow:hidden inline sur les ancêtres du tab-list
  //    (le parent direct génère overflow:hidden via style inline React)
  function fixOverflows() {
    doc.querySelectorAll('[data-baseweb="tab-list"]').forEach(function(tabList) {
      var el = tabList.parentElement;
      var depth = 0;
      while (el && depth < 8) {
        el.style.setProperty('overflow', 'visible', 'important');
        var tid = el.getAttribute('data-testid') || '';
        if (tid === 'stMain') break;
        el = el.parentElement;
        depth++;
      }
    });
  }

  // 3. MutationObserver — réappliquer après chaque re-render Streamlit
  function start() {
    if (!doc.body) { setTimeout(start, 100); return; }
    new MutationObserver(fixOverflows).observe(doc.body, { childList: true, subtree: true });
    fixOverflows();
  }
  start();
  setTimeout(fixOverflows, 600);
  setTimeout(fixOverflows, 1500);
})();
</script>""", height=0, scrolling=False)


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
    # Stratégie : session_state + _sid URL param (SQLite store).
    # La session est créée dans _finalize_login() et éteinte via logout().
    from dashboard.auth import get_session, has_role, render_auth, logout, load_users_config
    session = get_session()
    # Robustesse F5 : si session valide mais _sid absent de l'URL (ex: navigation sans _sid),
    # le remettre immédiatement pour que le prochain F5 fonctionne aussi.
    if session:
        _sid_in_state = st.session_state.get("_session_id", "")
        if _sid_in_state and not st.query_params.get("_sid"):
            st.query_params["_sid"] = _sid_in_state
    st.session_state["admin_authenticated"] = has_role(session, "back")
    st.session_state["username"] = session.get("username", "") if session else ""
    st.session_state["_suppress_auth_ui"] = bool(session)
    if has_role(session, "back"):
        # Empêche l'affichage résiduel des écrans TOTP après authentification réussie.
        st.session_state.pop("_auth_step", None)
        st.session_state.pop("_auth_pending_user", None)
        st.session_state.pop("_auth_totp_new_secret", None)

    users_cfg = load_users_config()
    guest_mode = users_cfg.get("settings", {}).get("guest_mode", True)

    # localStorage JS — permet de retrouver la session même si _sid disparaît de l'URL.
    _inject_session_persistence_js(bool(session))

    _inject_theme_css()
    render_header()

    show_admin = st.query_params.get("admin", "0") == "1"

    if show_admin:
        # ── VUE ADMINISTRATION ──
        if not has_role(session, "back"):
            # Tout le contenu d'auth est dans UN seul slot effaçable.
            # _render_totp_verify / _render_totp_setup appellent
            # st.session_state["_auth_slot"].empty() avant st.rerun()
            # pour vider atomiquement titre + info + formulaire → zéro artefact.
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
            # Front protégé
            render_auth()
        else:
            # Auto-refresh géré via JS dans la navbar (window.location.reload toutes 90s)
            # → pas de rerun Streamlit, pas d'effet grisé

            last_cycle = _get_last_cycle()
            portfolio  = _get_portfolio()          # consolidé (vue globale)
            _get_pnl_history()

            from dashboard.multi_asset import render_asset_tabs

            def _render_for_asset(asset: str):
                """Render complet pour un actif donné (utilisé par render_asset_tabs)."""
                _lc = _get_recent_decisions(1, asset=asset)
                # Ne pas fallback sur BTC : si aucune décision pour cet actif → état vide
                _lc = _lc[0] if _lc else None
                _tr = _get_recent_trades(200, asset=asset)
                _pf = _get_portfolio(asset=asset)   # portefeuille isolé pour cet actif
                render_portfolio(_pf)
                render_climate_metrics(_lc)
                render_v2_quant_state(asset)
                render_last_decision(_lc)
                render_trades_list(_tr)
                render_pnl_chart(_tr, key=f"pnl_chart_{asset.replace('/', '_')}")
                render_live_chart(asset)
                render_live_logs(key=asset.replace('/', '_'), asset=asset)

            def _render_portfolio_first():
                """Portefeuille global — affiché en tête de la vue Global."""
                render_portfolio(portfolio)

            def _render_global():
                """Vue consolidée : PnL tous actifs + logs."""
                _tr_all = _get_recent_trades(500)
                render_trades_list_sortable(_tr_all)
                render_pnl_chart(_tr_all, key="pnl_chart_global")
                render_live_logs(key="global")

            render_asset_tabs(_render_for_asset, global_fn=_render_global, pre_global_fn=_render_portfolio_first)
            st.markdown(
                '<div style="text-align:center;padding:24px 0 8px;'
                'font-size:11px;opacity:0.35;">Atlas Trader &mdash; by Jako 2026</div>',
                unsafe_allow_html=True,
            )

if __name__ == "__main__":
    main()
