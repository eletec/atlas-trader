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
    initial_sidebar_state="expanded",
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
        /* Sidebar nav — style radio items (light) */
        [data-testid="stSidebar"] [data-testid="stRadio"] label {
            padding: 9px 12px !important;
            border-radius: 6px !important;
            cursor: pointer !important;
            font-size: 14px !important;
            display: flex !important;
            align-items: center !important;
            gap: 8px !important;
        }
        [data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
            background: rgba(0,0,0,0.06) !important;
        }
        [data-testid="stSidebar"] [data-baseweb="radio"] { display: none !important; }
        /* Bouton rouvrir sidebar (quand pliée) — light */
        [data-testid="stSidebarCollapsedControl"] {
            background: #e9ecef !important;
            border-radius: 0 10px 10px 0 !important;
            box-shadow: 3px 0 12px rgba(0,0,0,0.2) !important;
            width: 36px !important;
            height: 48px !important;
            top: 50% !important;
            transform: translateY(-50%) !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            position: fixed !important;
            left: 0 !important;
            z-index: 999 !important;
            border: 2px solid rgba(0,0,0,0.1) !important;
        }
        [data-testid="stSidebarCollapsedControl"] button {
            color: #ff4b4b !important;
            font-size: 20px !important;
            width: 36px !important;
            height: 48px !important;
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
        /* Sidebar nav — style radio items (dark) */
        [data-testid="stSidebar"] [data-testid="stRadio"] label {
            padding: 9px 12px !important;
            border-radius: 6px !important;
            cursor: pointer !important;
            font-size: 14px !important;
            color: #FAFAFA !important;
            display: flex !important;
            align-items: center !important;
            gap: 8px !important;
        }
        [data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
            background: rgba(255,255,255,0.07) !important;
        }
        [data-testid="stSidebar"] [data-baseweb="radio"] { display: none !important; }
        /* Bouton rouvrir sidebar (quand pliée) — dark */
        [data-testid="stSidebarCollapsedControl"] {
            background: #21262d !important;
            border-radius: 0 10px 10px 0 !important;
            box-shadow: 3px 0 12px rgba(0,0,0,0.6) !important;
            width: 36px !important;
            height: 48px !important;
            top: 50% !important;
            transform: translateY(-50%) !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            position: fixed !important;
            left: 0 !important;
            z-index: 999 !important;
            border: 1px solid rgba(255,255,255,0.15) !important;
        }
        [data-testid="stSidebarCollapsedControl"] button {
            color: #ff4b4b !important;
            font-size: 20px !important;
            width: 36px !important;
            height: 48px !important;
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

    # CSS global : onglets scrollables horizontalement
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
button[data-testid="stTooltipIcon"],
[data-testid="stTooltipHoverTarget"],
[data-testid="stTooltipIcon"] {{
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
button[data-testid="stTooltipIcon"]:hover,
[data-testid="stTooltipHoverTarget"]:hover,
[data-testid="stTooltipIcon"]:hover {{
    background: {_t_icon_bg_h} !important;
    border-color: {_t_icon_fg_h} !important;
    color: {_t_icon_fg_h} !important;
}}
/* SVG — taille 16px, couleur héritée du bouton */
button[data-testid="stTooltipHoverTarget"] svg,
button[data-testid="stTooltipIcon"] svg,
[data-testid="stTooltipHoverTarget"] svg,
[data-testid="stTooltipIcon"] svg {{
    width: 16px !important;
    height: 16px !important;
    overflow: visible !important;
    color: inherit !important;
}}
/* Masquer le <circle> intégré au SVG — le bouton joue déjà le rôle du cercle.
   Sans cela, le SVG stroke-based dessine un 2e cercle par-dessus le rond CSS. */
button[data-testid="stTooltipHoverTarget"] svg circle,
button[data-testid="stTooltipIcon"] svg circle,
[data-testid="stTooltipHoverTarget"] svg circle,
[data-testid="stTooltipIcon"] svg circle {{
    display: none !important;
}}
/* Forcer la couleur du glyphe ? (path + point) — stroke ET fill pour les 2 variantes */
button[data-testid="stTooltipHoverTarget"] svg path,
button[data-testid="stTooltipIcon"] svg path,
[data-testid="stTooltipHoverTarget"] svg path,
[data-testid="stTooltipIcon"] svg path,
button[data-testid="stTooltipHoverTarget"] svg line,
button[data-testid="stTooltipIcon"] svg line,
[data-testid="stTooltipHoverTarget"] svg line,
[data-testid="stTooltipIcon"] svg line {{
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

def _force_run_background(asset: str, log_q) -> None:
    """
    Exécute le cycle complet depuis un thread background.
    Poste des chaînes HTML dans log_q au fur et à mesure.
    Poste ("__done__", (is_error: bool, message: str)) en dernier.
    """
    import time as _time
    import threading as _threading
    import logging
    from utils.i18n import t as _t
    from graph.workflow import (
        create_initial_state,
        node_fetch_news, node_crawl_web, node_run_mirofish,
        node_fetch_market_data, node_analyze_agents, node_synthesize,
        node_calculate_score, node_decide, node_execute,
        should_continue_after_news, should_execute,
    )

    _logger = logging.getLogger("zeitgeist.workflow")

    def _log(txt):
        log_q.put(txt)

    def _log_sub(txt):
        log_q.put(f"<span style='font-size:12px;opacity:0.7;padding-left:12px'>{txt}</span>")

    _STEP_TIMEOUTS = {
        "fetch_news": 45, "crawl_web": 90, "run_mirofish": 45,
        "fetch_market": 45, "agents": 210, "synthesize": 120,
        "score": 20, "decide": 20,
    }

    def _run_step(step_key, fn, s, timeout_s):
        _res = [None]; _err = [None]
        def _w():
            try:
                _res[0] = fn(s)
            except Exception as e:
                _err[0] = e
        thr = _threading.Thread(target=_w, daemon=True, name=f"frd_{step_key}")
        thr.start()
        thr.join(timeout=timeout_s)
        if thr.is_alive():
            return None, TimeoutError(f"timeout {timeout_s}s — nœud bloqué")
        if _err[0] is not None:
            return None, _err[0]
        return _res[0], None

    STEPS = [
        ("fetch_news",   _t("run_step_news"),    node_fetch_news),
        ("crawl_web",    _t("run_step_crawl"),   node_crawl_web),
        ("run_mirofish", _t("run_step_mirofish"),node_run_mirofish),
        ("fetch_market", _t("run_step_market"),  node_fetch_market_data),
        ("agents",       _t("run_step_agents"),  node_analyze_agents),
        ("synthesize",   _t("run_step_synth"),   node_synthesize),
        ("score",        _t("run_step_score"),   node_calculate_score),
        ("decide",       _t("run_step_decide"),  node_decide),
    ]

    start_ts = _time.strftime("%Y-%m-%d %H:%M:%S")
    _logger.info(f"=== CYCLE DASHBOARD DÉBUT à {start_ts} — type: dashboard-force ({asset}) ===")

    state = create_initial_state(asset)
    t_total = _time.time()

    for key, label, fn in STEPS:
        _log(f"⏳ <b>{label}</b>")
        t0 = _time.time()
        try:
            patch, _step_err = _run_step(key, fn, state, _STEP_TIMEOUTS.get(key, 90))
            if _step_err:
                raise _step_err
            if patch:
                state.update(patch)
            elapsed_s = _time.time() - t0

            if key == "fetch_news":
                if should_continue_after_news(state) == "abort":
                    _log(f"⚠️ {_t('run_no_news_abort')}")
                    break
                n = len(state.get("news_items", []))
                _log(f"✅ <b>{label}</b> — {_t('run_news_count').format(n=n)} ({elapsed_s:.1f}s)")
            elif key == "crawl_web":
                st_ = state.get("crawler_status", "?")
                _log(f"✅ <b>{label}</b> — {_t('run_status')}: {st_} ({elapsed_s:.1f}s)")
            elif key == "run_mirofish":
                mf = state.get("mirofish_result") or {}
                _log(f"✅ <b>{label}</b> — {_t('run_signal')}: {mf.get('signal','?')} {_t('run_conf')}: {mf.get('confidence',0):.0%} ({elapsed_s:.1f}s)")
            elif key == "fetch_market":
                mi = state.get("market_indicators") or {}
                _log(f"✅ <b>{label}</b> — BTC: ${mi.get('price',0):,.0f} RSI: {mi.get('rsi_14',0):.1f} ({elapsed_s:.1f}s)")
            elif key == "agents":
                analyses = state.get("agent_analyses", {})
                errs_n = len(state.get("errors", []))
                for aname, adata in analyses.items():
                    if isinstance(adata, dict):
                        asig  = adata.get("signal", "?")
                        asc   = adata.get("score", 50)
                        aconf = adata.get("confidence", 0)
                        asum  = adata.get("summary", "")
                        if asig == "NEUTRAL" and aconf == 0:
                            _log_sub(f"⚠️ {aname} — fallback ({asum})")
                        else:
                            _log_sub(f"✓ {aname} — {asig} (score {asc:.0f}, conf {aconf:.0%})")
                _log(f"✅ <b>{label}</b> — {_t('run_agents_count').format(n=len(analyses), e=errs_n)} ({elapsed_s:.1f}s)")
            elif key == "synthesize":
                _log(f"✅ <b>{label}</b> — tokens: {state.get('llm_tokens_used', 0)} ({elapsed_s:.1f}s)")
            elif key == "score":
                _log(f"✅ <b>{label}</b> — score: {state.get('global_score', 0):.1f}/100 ({elapsed_s:.1f}s)")
            elif key == "decide":
                action = (state.get("decision") or {}).get("action", "HOLD")
                _log(f"✅ <b>{label}</b> — <b>{action}</b> ({elapsed_s:.1f}s)")
                if should_execute(state) == "execute":
                    _log(f"⏳ <b>{_t('run_trade_exec')} ({action})</b>")
                    t0e = _time.time()
                    try:
                        patch, _exec_err = _run_step("execute", node_execute, state, 30)
                        if _exec_err:
                            raise _exec_err
                        if patch:
                            state.update(patch)
                        tr = state.get("trade_result") or {}
                        _log(f"✅ <b>{_t('run_trade_done')}</b> — {tr.get('status','?')} ({_time.time()-t0e:.1f}s)")
                    except Exception as exc:
                        _log(f"❌ <b>{_t('run_trade_failed')}</b> — {exc}")
        except Exception as exc:
            _log(f"❌ <b>{label}</b> — {exc} ({_time.time()-t0:.1f}s)")
            state.setdefault("errors", []).append(f"{key}: {exc}")

    total_s = _time.time() - t_total
    state["cycle_duration_ms"] = int(total_s * 1000)
    errs = state.get("errors", [])
    final_action = (state.get("decision") or {}).get("action", "N/A")
    final_score  = state.get("global_score", 0)

    end_ts = _time.strftime("%Y-%m-%d %H:%M:%S")
    _logger.info(
        f"=== CYCLE DASHBOARD FIN à {end_ts} — "
        f"{total_s:.1f}s | score={final_score:.1f} | "
        f"decision={final_action} | erreurs={len(errs)} ==="
    )
    if errs:
        msg = f"{_t('run_done_errors').format(n=len(errs))} — {final_action} | score {final_score:.0f} | {total_s:.1f}s"
    else:
        msg = f"{_t('run_done')} — {final_action} | score {final_score:.0f} | {total_s:.1f}s"
    log_q.put(("__done__", (bool(errs), msg)))


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
        cfg   = _get_settings()
        st.session_state["_force_run_asset"] = cfg.get("project", {}).get("asset", "BTC/USDT")

    if st.session_state.get("_force_run_asset"):
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
    admin_label = f"{admin_icon}&nbsp; {t('hbg_admin')}"
    admin_bg    = f"background:rgba(255,75,75,0.18);" if show_admin else ""

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
    <span style="font-weight:400;font-size:12px;opacity:0.5;"> &middot; Paper Trading BTC/USDT</span>
  </span>
  <span style="font-size:12px;color:{nav_fg};opacity:0.6;white-space:nowrap;flex-shrink:0;font-variant-numeric:tabular-nums;">{_fmt_utc_local(datetime.utcnow())}</span>
  <a href="{u_refresh}" style="{S_BTN}" title="{t('hbg_refresh')}" target="_self"><i class="fas fa-rotate-right"></i></a>
  <a href="{u_force}" style="{S_BTN}" title="Force Run" target="_self"
     class="{'atlas-bolt-active' if _cycle_locked else ('atlas-bolt-alive' if _daemon_alive else '')}"><i class="fas fa-bolt"></i></a>
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

    time_ago = "—"
    if ts:
        try:
            diff = int((datetime.utcnow() - datetime.fromisoformat(ts)).total_seconds() / 60)
            time_ago = f"{diff} min" if diff < 60 else f"{diff // 60} h"
        except Exception:
            pass

    # Indicateur propre à l'asset :
    #  - ⟳ en cours  : lock actif pour cet asset
    #  - ✓ actif     : heartbeat de cet asset < 30 min (cycles récents)
    #  - 🌙 hors session : heartbeat de cet asset > 30 min (forex fermé, etc.)
    _asset_hb = f"/tmp/atlas_heartbeat_{asset}" if asset else None
    _asset_slash = asset.replace("_", "/") if asset else None
    if _is_cycle_locked(_asset_slash):
        time_ago += ' <span style="color:#22c55e;font-size:11px;">⟳ en cours</span>'
    elif _asset_hb and _cm_os.path.exists(_asset_hb):
        _hb_age = _cm_time.time() - _cm_os.path.getmtime(_asset_hb)
        if _hb_age < 1800:
            time_ago += ' <span style="color:#22c55e;font-size:11px;">✓ actif</span>'
        else:
            # Calcul heure de reprise via MarketSession
            _next_label = ""
            try:
                from utils.session import MarketSession as _MarketSession
                _sess = _MarketSession(_asset_slash or "BTC/USDT")
                _nxt = _sess.next_open()
                _nxt_utc = _nxt.strftime("%H:%M UTC")
                _wait_min = int((_nxt - __import__('datetime').datetime.now(
                    __import__('datetime').timezone.utc)).total_seconds() / 60)
                if _wait_min < 60:
                    _next_label = f" — reprise dans {_wait_min} min ({_nxt_utc})"
                elif _wait_min < 1440:
                    _next_label = f" — reprise à {_nxt_utc}"
                else:
                    _nxt_day = _nxt.strftime("%a %H:%M UTC")
                    _next_label = f" — reprise {_nxt_day}"
            except Exception:
                pass
            time_ago += (
                f' <span style="color:#888;font-size:11px;">'
                f'🌙 hors session{_next_label}</span>'
            )

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
    st.plotly_chart(fig, use_container_width=True, key=key)


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


def render_trades_list_sortable(trades: list[dict]):
    """Historique global des trades — triable par clic sur entête (HTML+JS)."""
    st.markdown(
        '<h3 style="margin:16px 0 12px;font-size:18px;">'
        '<i class="fas fa-clock-rotate-left" style="margin-right:8px;color:#7986cb;"></i>'
        'Historique des trades — tous actifs</h3>',
        unsafe_allow_html=True,
    )
    if not trades:
        st.info(t("no_trades"))
        return

    import json as _json

    theme = _get_theme()
    if theme == "light":
        tbl_bg  = "#ffffff"; tbl_fg  = "#212529"
        head_bg = "#f1f3f5"; row_alt = "#f8f9fa"
        border  = "#dee2e6"; sep     = "#e9ecef"
        hov     = "#e9ecef"
    else:
        tbl_bg  = "#161b22"; tbl_fg  = "#e6edf3"
        head_bg = "#0d1117"; row_alt = "#1b2129"
        border  = "rgba(255,255,255,0.08)"; sep = "rgba(255,255,255,0.05)"
        hov     = "#21262d"

    # Unique ID to avoid JS collision if called multiple times
    tid = "gtrades"

    cols = ["Date", "Actif", "Action", "Entrée", "Taille", "SL", "TP", "P&L", "Score"]

    header_cells = "".join(
        f'<th onclick="sortTable(\'{tid}\',{i})" '
        f'style="padding:9px 12px;font-size:12px;font-weight:600;'
        f'text-transform:uppercase;letter-spacing:.05em;color:{tbl_fg};'
        f'opacity:.8;background:{head_bg};white-space:nowrap;'
        f'border-bottom:2px solid {border};cursor:pointer;user-select:none;" '
        f'title="Cliquer pour trier">{c} <span style="opacity:.4;">⇅</span></th>'
        for i, c in enumerate(cols)
    )

    rows_html = ""
    for i, trade in enumerate(trades):
        pnl    = trade.get("result_24h")
        action = trade.get("action", "")
        bg     = row_alt if i % 2 == 1 else tbl_bg

        action_color = "#2ecc71" if action == "BUY" else ("#e74c3c" if action == "SELL" else tbl_fg)
        if action == "SELL":
            pnl_str = f'<span style="opacity:.6;font-style:italic;">✓ Clôture</span>'
        elif pnl is None:
            pnl_str = f'<span style="opacity:.45;">{t("pending")}</span>'
        elif pnl >= 0:
            pnl_str = f'<span style="color:#2ecc71;font-weight:600;">${pnl:+,.2f}</span>'
        else:
            pnl_str = f'<span style="color:#e74c3c;font-weight:600;">${pnl:+,.2f}</span>'

        asset = trade.get("asset", "—")
        cells = [
            trade.get("timestamp", "")[:16].replace("T", " "),
            f'<span style="font-weight:600;color:#7986cb;">{asset}</span>',
            f'<span style="color:{action_color};font-weight:600;">{action}</span>',
            f'${trade.get("entry_price", 0):,.2f}'    if trade.get("entry_price")    else "—",
            f'${trade.get("position_size", 0):,.0f}'  if trade.get("position_size")  else "—",
            f'${trade.get("sl_price", 0):,.2f}'       if trade.get("sl_price")       else "—",
            f'${trade.get("tp_price", 0):,.2f}'       if trade.get("tp_price")       else "—",
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
  <table id="{tid}" style="border-collapse:collapse;width:100%;min-width:800px;">
    <thead><tr>{header_cells}</tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>
<script>
(function(){{
  var _dirs = {{}};
  function sortTable(id, col) {{
    var tbl = document.getElementById(id);
    if (!tbl) return;
    var tbody = tbl.tBodies[0];
    var rows  = Array.from(tbody.rows);
    _dirs[id] = _dirs[id] || {{}};
    var asc   = !_dirs[id][col];
    _dirs[id][col] = asc;
    rows.sort(function(a, b) {{
      var av = a.cells[col] ? a.cells[col].innerText.replace(/[^0-9.+\-]/g,'') : '';
      var bv = b.cells[col] ? b.cells[col].innerText.replace(/[^0-9.+\-]/g,'') : '';
      var an = parseFloat(av), bn = parseFloat(bv);
      if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
      return asc ? av.localeCompare(bv) : bv.localeCompare(av);
    }});
    rows.forEach(function(r){{ tbody.appendChild(r); }});
  }}
  window.sortTable = sortTable;
}})();
</script>"""
    st.markdown(html, unsafe_allow_html=True)


def render_last_decision(last_cycle: dict | None):
    """Affiche la dernière décision avec explication IA et breakdown des scores."""
    st.markdown('<div style="margin-top:24px;"></div>', unsafe_allow_html=True)
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
            ts_label = _fmt_utc_local(dt)
        except Exception:
            ts_label = ts[:16]

    st.markdown(
        f"<div style='border-left:4px solid {action_color}; padding:12px; "
        f"border-radius:4px;'>"
        f"<strong style='color:{action_color}'>{action}</strong> — "
        f"Score: {last_cycle.get('score', 0):.0f}/100"
        + (f" &nbsp;<span style='font-size:11px;opacity:0.55;'>🕐 {ts_label}</span>" if ts_label else "")
        + f"<br><br>{explanation}</div>",
        unsafe_allow_html=True
    )

    # F11 — Score breakdown : contribution de chaque composant
    breakdown = last_cycle.get("breakdown") or last_cycle.get("score_breakdown") or {}
    if isinstance(breakdown, str):
        try:
            import json as _json
            breakdown = _json.loads(breakdown)
        except Exception:
            breakdown = {}
    if breakdown:
        parts = []
        for name, data in breakdown.items():
            if name == "final_score":
                continue
            if not isinstance(data, dict):
                continue
            component_score = data.get("score", 0)
            weight = data.get("weight", 0)
            contribution = data.get("contribution", component_score * weight)
            parts.append(
                f'<span style="margin-right:10px;white-space:nowrap;">'
                f'<strong>{name}</strong>: {component_score:.0f} '
                f'<span style="opacity:0.55;">×{weight:.0%}</span> '
                f'= <strong>{contribution:.1f}</strong></span>'
            )
        if parts:
            st.markdown(
                f'<div style="font-size:12px;margin-top:8px;opacity:0.75;">'
                f'{"".join(parts)}</div>',
                unsafe_allow_html=True,
            )


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


def render_live_logs(key: str = "global"):
    """Affiche tous les logs avec pagination (100 lignes par page)."""
    st.markdown(
        f'<h3 style="margin:0 0 12px;font-size:18px;">'
        f'<i class="fas fa-terminal" style="margin-right:8px;color:#7986cb;"></i>'
        f'{t("logs_title")}</h3>',
        unsafe_allow_html=True,
    )
    try:
        from storage.database import get_connection
        with get_connection() as conn:
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
        st.caption(f"{total_rows} lignes · {total_pages} page{'s' if total_pages > 1 else ''}")
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
            '<p style="font-size:11px;color:#888;margin:0 0 10px;">'
            '⚠️ Les profils shadow utilisent un capital virtuel de $10 000 qui évolue avec les P&L '
            '(sizing proportionnel au capital restant). Seul <strong>Baseline</strong> reflète '
            'le capital réel. Le rendement <strong>%</strong> est la métrique fiable pour comparer.</p>',
            unsafe_allow_html=True,
        )

        cols = ["Profil", t("profiles_trades"), t("profiles_winrate"),
                "Rendement %", "Capital virtuel", t("profiles_avg_pnl"), "Best", "Worst"]
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
                    label = cfg.get("label", name)
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
                f' <span style="color:#888;font-size:11px;">({s["evaluated"]} éval.)</span>{sample_warn}</td>'
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
                        label = cfg.get("label", name)
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
                yaxis_title="Rendement %",
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

    sub_tabs = st.tabs([
        f"⚙ {t('tab_llm')}",
        f"⛏ {t('tab_crawler')}",
        f"◈ {t('tab_news')}",
        f"⊛ {t('tab_sources')}",
        f"◇ {t('tab_mirofish')}",
        f"⚖ {t('tab_risk')}",
        f"⬡ {t('tab_agents')}",
        f"≡ {t('tab_logging')}",
        f"⏱ {t('tab_timesfm')}",
        "📊 Agents Perf",
        "🔍 Méta-Analyse",
        f"⊞ {t('tab_market_regime')}",
        f"⇄ {t('tab_flux')}",
        f"👤 {t('tab_users')}",
        " Par Actif",
    ])

    with sub_tabs[0]:  # LLM
        st.markdown(f'<h4><i class="fas fa-microchip" style="margin-right:7px;color:#7986cb;"></i>{t("cfg_llm_title")}</h4>', unsafe_allow_html=True)
        st.info(t("cfg_llm_info"))
        llm = settings.get("llm", {})
        col1, col2 = st.columns(2)
        with col1:
            _llm_providers = ["anthropic", "deepseek", "openai", "xai", "ollama"]
            _llm_default = llm.get("provider", "anthropic")
            if _llm_default not in _llm_providers:
                _llm_providers.append(_llm_default)
            llm["provider"] = st.radio(t("cfg_provider"), _llm_providers,
                index=_llm_providers.index(_llm_default),
                horizontal=True, help=t("cfg_provider_help"))
            llm["model"] = st.text_input(t("cfg_model"), value=llm.get("model", "claude-3-5-sonnet-20241022"),
                help=t("cfg_model_help"))
        with col2:
            llm["temperature"] = st.slider(t("cfg_temperature"), 0.0, 1.0,
                float(llm.get("temperature", 0.3)), 0.05,
                help=t("cfg_temperature_help"))
            llm["max_tokens"] = st.number_input(t("cfg_max_tokens"), 512, 8192,
                int(llm.get("max_tokens", 4096)), step=512,
                help=t("cfg_max_tokens_help"))
            llm["request_timeout_seconds"] = st.number_input(
                t("cfg_timeout_llm"),
                min_value=10, max_value=300,
                value=int(llm.get("request_timeout_seconds", 60)),
                step=10,
                help=t("cfg_timeout_help")
            )
        llm["cache_responses"] = st.toggle(t("cfg_cache_responses"), llm.get("cache_responses", True),
            help=t("cfg_cache_help"))

        # Clés API par provider
        st.markdown(f"**{t('cfg_api_keys')}**")
        _provider_now = llm.get("provider", "anthropic")
        import os as _os
        _key_labels = {
            "anthropic": ("Anthropic API Key", "ANTHROPIC_API_KEY", "anthropic_api_key"),
            "deepseek":  ("DeepSeek API Key",  "DEEPSEEK_API_KEY",  "deepseek_api_key"),
            "openai":    ("OpenAI API Key",    "OPENAI_API_KEY",    "openai_api_key"),
            "xai":       ("xAI API Key",       "XAI_API_KEY",       "xai_api_key"),
            "ollama":    ("Ollama Base URL",   "OLLAMA_BASE_URL",   "ollama_base_url"),
        }
        _lbl, _env_var, _cfg_key = _key_labels.get(_provider_now, (f"{_provider_now} API Key", "", f"{_provider_now}_api_key"))
        _current_val = llm.get(_cfg_key) or _os.environ.get(_env_var, "")
        _new_val = st.text_input(
            _lbl,
            value=_current_val,
            type="password",
            help=t("cfg_api_key_saved").format(env=_env_var),
            key=f"llm_api_key_{_provider_now}",
        )
        if _new_val:
            llm[_cfg_key] = _new_val
        settings["llm"] = llm

        # CA7 — Section "Analyser avec le LLM" (utilise le provider configuré)
        st.divider()
        _provider_label = llm.get("provider", "LLM").capitalize()
        st.markdown(
            f"<h4><i class=\"fas fa-terminal\" style=\"margin-right:7px;color:#7986cb;\"></i>"
            f"{t('cfg_analyze_with').format(provider=_provider_label)}</h4>",
            unsafe_allow_html=True,
        )
        # Clé API du provider actif (lecture seule pour info ; éditable via champ dédié ci-dessus)
        import os as _os
        _prov = llm.get("provider", "anthropic")
        _key_map = {
            "anthropic": ("anthropic_api_key", "ANTHROPIC_API_KEY"),
            "deepseek":  ("deepseek_api_key",  "DEEPSEEK_API_KEY"),
            "openai":    ("openai_api_key",     "OPENAI_API_KEY"),
            "xai":       ("xai_api_key",        "XAI_API_KEY"),
            "github":    ("github_api_key",     "GITHUB_TOKEN"),
            "ollama":    ("ollama_base_url",     "OLLAMA_BASE_URL"),
        }
        _cfg_k, _env_k = _key_map.get(_prov, (f"{_prov}_api_key", ""))
        _cur_key = llm.get(_cfg_k) or _os.environ.get(_env_k, "")
        _placeholder = _cur_key if (_cur_key and not _cur_key.endswith("...")) else ""
        _new_key = st.text_input(
            t("cfg_api_key_for_prov").format(provider=_provider_label),
            value=_placeholder,
            type="password",
            help=t("cfg_api_key_saved2").format(env=_env_k),
            key=f"ca7_key_{_prov}",
        )
        if _new_key:
            llm[_cfg_k] = _new_key
            settings["llm"] = llm
        claude_prompt = st.text_area(
            t("cfg_ca7_prompt"),
            value=t("cfg_ca7_default_prompt"),
            height=100,
            key="ca7_claude_prompt",
        )
        ca7_col1, ca7_col2 = st.columns([1, 3])
        with ca7_col1:
            ca7_timeout = st.number_input(t("cfg_ca7_timeout"), min_value=10, max_value=300,
                                          value=60, step=10, key="ca7_timeout")
        with ca7_col2:
            ca7_inject = st.toggle(t("cfg_ca7_inject"), value=True, key="ca7_inject")
        if st.button(t("cfg_ca7_run").format(provider=_provider_label), key="ca7_run_btn"):
            with st.spinner("Analyse en cours…"):
                try:
                    from utils.claude_cli import run_claude_analysis
                    _full_prompt = claude_prompt
                    if ca7_inject:
                        import json as _json
                        _ctx_parts = []
                        try:
                            from storage.database import get_recent_decisions, get_recent_trades
                            _decisions = get_recent_decisions(10)
                            if _decisions:
                                _ctx_parts.append("## Dernières décisions du système (JSON)\n```json\n"
                                    + _json.dumps(_decisions, ensure_ascii=False, indent=2, default=str)
                                    + "\n```")
                            _trades = get_recent_trades(5)
                            if _trades:
                                _ctx_parts.append("## Derniers trades BUY/SELL\n```json\n"
                                    + _json.dumps(_trades, ensure_ascii=False, indent=2, default=str)
                                    + "\n```")
                        except Exception as _db_exc:
                            _ctx_parts.append(f"*(données DB indisponibles : {_db_exc})*")
                        try:
                            _port = _get_portfolio()
                            _ctx_parts.append(
                                f"## Portfolio actuel\n"
                                f"- Capital : {_port.get('capital', '?')} USDT\n"
                                f"- Valeur : {_port.get('current_value', '?')} USDT\n"
                                f"- PnL total : {_port.get('total_pnl', '?')} USDT "
                                f"({_port.get('total_pnl_pct', '?')}%)\n"
                                f"- Nb trades : {_port.get('n_trades', '?')}"
                            )
                        except Exception:
                            pass
                        if _ctx_parts:
                            _full_prompt = (
                                "Tu es un assistant de trading algorithmique. "
                                "Voici les données réelles du système Atlas Trader :\n\n"
                                + "\n\n".join(_ctx_parts)
                                + "\n\n---\n\n"
                                + claude_prompt
                            )
                    ca7_result = run_claude_analysis(_full_prompt, timeout=int(ca7_timeout))
                    st.text_area(t("cfg_ca7_result"), value=ca7_result, height=300, key="ca7_result")
                except Exception as _ca7_exc:
                    st.error(f"Erreur : {_ca7_exc}")

    with sub_tabs[1]:  # Crawler
        st.markdown(f'<h4><i class="fas fa-spider" style="margin-right:7px;color:#7986cb;"></i>{t("cfg_crawler_title")}</h4>', unsafe_allow_html=True)
        st.info(t("cfg_crawler_info"))
        crawler = settings.get("crawler", {})
        col1, col2 = st.columns(2)
        with col1:
            _crawler_providers = ["tavily", "firecrawl", "serpapi", "duckduckgo"]
            _crawler_default = crawler.get("provider", "tavily")
            if _crawler_default not in _crawler_providers:
                _crawler_providers.append(_crawler_default)
            crawler["provider"] = st.radio(t("cfg_provider"), _crawler_providers,
                index=_crawler_providers.index(_crawler_default), key="crawler_provider",
                horizontal=True, help=t("cfg_provider_help"))
            crawler["n_themes"] = st.slider(t("cfg_n_themes"), 5, 15, int(crawler.get("n_themes", 10)),
                help=t("cfg_n_themes_help"))
        with col2:
            crawler["max_pages_per_theme"] = st.slider(t("cfg_pages_theme"), 3, 20,
                int(crawler.get("max_pages_per_theme", 10)),
                help=t("cfg_pages_theme_help"))
            _freq_opts = ["daily", "per_cycle", "trigger"]
            _freq_default = crawler.get("frequency", "daily")
            if _freq_default not in _freq_opts:
                _freq_opts.append(_freq_default)
            crawler["frequency"] = st.radio(t("cfg_frequency"), _freq_opts,
                index=_freq_opts.index(_freq_default),
                horizontal=True, help=t("cfg_frequency_help"))
        _cr_all_assets = list(settings.get("project", {}).get("active_assets",
                         ["BTC/USDT", "ETH/USDT", "XAU/USD", "EUR/USD", "GBP/USD"]))
        _cr_icons = {"BTC/USDT": "₿", "ETH/USDT": "⟠", "XAU/USD": "◎", "EUR/USD": "€", "GBP/USD": "£"}
        _cr_subtabs = st.tabs(["🌐 Macro"] + [f"{_cr_icons.get(a,'◆')} {a.split('/')[0]}" for a in _cr_all_assets])
        with _cr_subtabs[0]:
            _macro_raw = st.text_area(
                t("cfg_templates"),
                value="\n".join(crawler.get("templates_macro", crawler.get("templates", []))),
                key="crawler_templates_macro", height=200,
                help="Templates communs à TOUS les actifs. {asset} et {year} sont remplacés dynamiquement."
            )
            crawler["templates_macro"] = [
                l.strip() for l in _macro_raw.splitlines()
                if l.strip() and not l.strip().startswith("#")
            ]
            st.caption(f"{len(crawler['templates_macro'])} templates macro configurés")
        for _ci, _ca in enumerate(_cr_all_assets):
            with _cr_subtabs[_ci + 1]:
                try:
                    from utils.config import load_asset_config as _cr_lac, save_asset_config as _cr_sac
                    _cr_acfg = _cr_lac(_ca)
                except Exception:
                    _cr_acfg = {}
                _cr_tmpl = _cr_acfg.get("crawler", {}).get("templates", [])
                _cr_new = st.text_area(
                    f"Templates spécifiques {_ca}",
                    value="\n".join(_cr_tmpl),
                    key=f"cr_tmpl_{_ca.replace('/', '_')}",
                    height=200,
                    help=f"{{{{asset}}}} → {_ca.split('/')[0]}, {{{{year}}}} → année courante. "
                         "Ajoutés AUX templates macro globaux."
                )
                _cr_acfg.setdefault("crawler", {})["templates"] = [
                    l.strip() for l in _cr_new.splitlines()
                    if l.strip() and not l.strip().startswith("#")
                ]
                st.caption(f"{len(_cr_acfg['crawler']['templates'])} templates spécifiques")
                if st.button(f"💾 Sauvegarder templates {_ca}", key=f"cr_save_{_ca.replace('/', '_')}",
                             type="primary", use_container_width=True):
                    try:
                        from utils.config import save_asset_config as _cr_sac2
                        _cr_sac2(_ca, _cr_acfg)
                        st.success(f"✅ Templates {_ca} sauvegardés")
                    except Exception as _ce:
                        st.error(f"❌ Erreur : {_ce}")
        settings["crawler"] = crawler

    with sub_tabs[2]:  # News
        st.markdown(f'<h4><i class="fas fa-newspaper" style="margin-right:7px;color:#7986cb;"></i>{t("cfg_news_title")}</h4>', unsafe_allow_html=True)
        st.info(t("cfg_news_info"))
        news = settings.get("news", {})
        col1, col2 = st.columns(2)
        with col1:
            news["polling_interval_seconds"] = st.slider(
                t("cfg_polling_interval"), 60, 3600,
                int(news.get("polling_interval_seconds", 900)), step=60,
                help=t("cfg_polling_interval_help")
            )
        with col2:
            news["max_items_per_cycle"] = st.number_input(
                t("cfg_items_max_cycle"), 10, 200, int(news.get("max_items_per_cycle", 30)),
                help=t("cfg_items_max_cycle_help")
            )
        # Mots-clés par actif
        sources_per_asset = news.get("sources_per_asset", {})
        _all_assets = list(settings.get("project", {}).get("active_assets",
                      ["BTC/USDT", "ETH/USDT", "XAU/USD", "EUR/USD", "GBP/USD"]))
        _kw_icons = {"BTC/USDT": "₿", "ETH/USDT": "⟠", "XAU/USD": "◎", "EUR/USD": "€", "GBP/USD": "£"}
        st.markdown("##### 🔑 Mots-clés de surveillance par actif")
        _kw_tabs = st.tabs([f"{_kw_icons.get(a,'◆')} {a.split('/')[0]}" for a in _all_assets])
        for _ki, _ka in enumerate(_all_assets):
            with _kw_tabs[_ki]:
                _kw_data = sources_per_asset.get(_ka, {})
                _kw_new = st.text_input(
                    "Mots-clés (séparés par virgules)",
                    value=", ".join(_kw_data.get("keywords", [])),
                    key=f"news_kw_{_ka.replace('/', '_')}"
                )
                _kw_data["keywords"] = [k.strip() for k in _kw_new.split(",") if k.strip()]
                sources_per_asset[_ka] = _kw_data
        news["sources_per_asset"] = sources_per_asset
        settings["news"] = news

    with sub_tabs[3]:  # Sources
        st.markdown(f'<h4><i class="fas fa-satellite-dish" style="margin-right:7px;color:#7986cb;"></i>{t("cfg_sources_title")}</h4>', unsafe_allow_html=True)
        st.info(t("cfg_sources_info"))
        news = settings.get("news", {})
        sources_per_asset = news.get("sources_per_asset", {})
        _all_assets_src = list(settings.get("project", {}).get("active_assets",
                           ["BTC/USDT", "ETH/USDT", "XAU/USD", "EUR/USD", "GBP/USD"]))

        # ── Sources macro (communes à tous les actifs) ──────────────────────
        st.markdown("#### 🌐 Sources macro \u2014 communes à tous les actifs")
        macro_raw = "\n".join(news.get("sources_rss_macro", []))
        macro_edited = st.text_area(
            "Flux RSS macro (un par ligne)",
            value=macro_raw, height=180, key="rss_macro",
            help="Géopolitique, économie, banques centrales… pertinents pour tous les actifs."
        )
        news["sources_rss_macro"] = [
            u.split("#")[0].strip()
            for u in macro_edited.splitlines()
            if u.strip() and not u.strip().startswith("#")
        ]
        st.caption(f"{len(news['sources_rss_macro'])} flux macro configurés")

        st.markdown("---")

        # ── Sources spécifiques par actif ───────────────────────────────────
        _src_icons = {"BTC/USDT": "₿", "ETH/USDT": "⟠", "XAU/USD": "◎", "EUR/USD": "€", "GBP/USD": "£"}
        _src_tabs = st.tabs([f"{_src_icons.get(a,'◆')} {a.split('/')[0]}" for a in _all_assets_src])
        for _si, _sa in enumerate(_all_assets_src):
            with _src_tabs[_si]:
                _src = sources_per_asset.get(_sa, {})

                # --- RSS ---
                st.markdown(f"#### 📰 {t('cfg_rss_title')}")
                rss_edited = st.text_area(
                    t("cfg_rss_area"),
                    value="\n".join(_src.get("rss", [])), height=220,
                    key=f"rss_sources_{_sa.replace('/', '_')}",
                    help="Un flux RSS par ligne. Lignes commençant par # ignorées."
                )
                _src["rss"] = [
                    u.split("#")[0].strip()
                    for u in rss_edited.splitlines()
                    if u.strip() and not u.strip().startswith("#")
                ]
                st.caption(t("cfg_rss_count").format(n=len(_src['rss'])))

                # --- Nitter ---
                st.markdown(f"#### 🐦 {t('cfg_nitter_title')}")
                nitter_edited = st.text_area(
                    t("cfg_nitter_area"),
                    value="\n".join(_src.get("nitter", [])), height=140,
                    key=f"nitter_sources_{_sa.replace('/', '_')}",
                    help="Un compte par ligne (sans @)."
                )
                _src["nitter"] = [
                    u.strip().lstrip("@")
                    for u in nitter_edited.splitlines()
                    if u.strip()
                ]
                st.caption(t("cfg_nitter_count").format(n=len(_src['nitter'])))

                # --- Reddit ---
                st.markdown(f"#### 🤖 {t('cfg_reddit_title')}")
                reddit_edited = st.text_area(
                    t("cfg_reddit_area"),
                    value="\n".join(_src.get("reddit", [])), height=100,
                    key=f"reddit_sources_{_sa.replace('/', '_')}",
                    help="Un subreddit par ligne (sans r/)."
                )
                _src["reddit"] = [
                    u.strip().lstrip("r/")
                    for u in reddit_edited.splitlines()
                    if u.strip()
                ]
                st.caption(t("cfg_reddit_count").format(n=len(_src['reddit'])))

                # --- CryptoPanic (crypto uniquement) ---
                _cp_map = news.get("cryptopanic", {}).get("asset_currency_map", {"BTC/USDT": "BTC", "ETH/USDT": "ETH"})
                if _sa in _cp_map:
                    st.markdown("#### 🚨 CryptoPanic")
                    cp = news.get("cryptopanic", {})
                    _cp_col1, _cp_col2 = st.columns(2)
                    with _cp_col1:
                        cp["enabled"] = st.toggle(t("cfg_cp_enable"), cp.get("enabled", True),
                                                   key=f"cp_enabled_{_sa.replace('/', '_')}")
                    with _cp_col2:
                        cp["max_items"] = st.number_input(
                            t("cfg_cp_max"), 5, 50, int(cp.get("max_items", 15)),
                            key=f"cp_max_{_sa.replace('/', '_')}")
                    news["cryptopanic"] = cp
                else:
                    st.caption("🚨 CryptoPanic : non applicable pour cet actif (crypto uniquement)")

                sources_per_asset[_sa] = _src
        news["sources_per_asset"] = sources_per_asset

        settings["news"] = news

    with sub_tabs[4]:  # MiroFish
        st.markdown(f'<h4><i class="fas fa-fish" style="margin-right:7px;color:#7986cb;"></i>{t("cfg_mirofish_title")}</h4>', unsafe_allow_html=True)
        st.info(t("cfg_mirofish_info"))
        mf = settings.get("mirofish", {})
        col1, col2 = st.columns(2)
        with col1:
            mf["n_agents"] = st.number_input(t("cfg_mf_agents"), 1000, 50000,
                int(mf.get("n_agents", 5000)), step=1000,
                help=t("cfg_mf_agents_help"))
            mf["n_steps"] = st.number_input(t("cfg_mf_steps"), 10, 500,
                int(mf.get("n_steps", 100)), step=10,
                help=t("cfg_mf_steps_help"))
        with col2:
            mf["seed_news_weight"] = st.slider(t("cfg_mf_news_weight"), 0.0, 1.0,
                float(mf.get("seed_news_weight", 0.6)), 0.05,
                help=t("cfg_mf_news_weight_help"))
            mf["air_du_temps_weight"] = 1 - mf["seed_news_weight"]
            st.metric(t("cfg_mf_adt_weight"), f"{mf['air_du_temps_weight']:.0%}")
        settings["mirofish"] = mf

    with sub_tabs[5]:  # Risk
        st.markdown(f'<h4><i class="fas fa-shield-halved" style="margin-right:7px;color:#7986cb;"></i>{t("cfg_risk_title")}</h4>', unsafe_allow_html=True)
        st.info(t("cfg_risk_info"))
        st.caption("💡 Mode, seuils BUY/EXIT, Kelly, drawdown, position size et filtre MA50 sont configurables **par actif** dans l'onglet **🎯 Par Actif**.")
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
        st.caption("💡 Le capital simulé par actif est configurable dans l'onglet **🎯 Par Actif**.")
        _testnet_current = exch.get("testnet", True)
        _testnet_new = st.toggle(t("cfg_testnet"), value=_testnet_current)
        exch["testnet"] = _testnet_new
        if not _testnet_new:
            st.error(t("cfg_testnet_warn"))
        settings["exchange"] = exch

    with sub_tabs[6]:  # Agents
        st.markdown(f'<h4><i class="fas fa-network-wired" style="margin-right:7px;color:#7986cb;"></i>{t("cfg_agents_title")}</h4>', unsafe_allow_html=True)
        st.info(t("cfg_agents_info"))
        agents = settings.get("agents", {})
        for agent_name in ["market_data", "fundamental", "x_sentiment", "contrarian", "fear_greed", "polymarket", "timesfm"]:
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

        # market_regime — info-only (weight toujours 0.0, configure via onglet dédié)
        st.markdown("---")
        mr_cfg = agents.get("market_regime", {})
        mr_cfg["enabled"] = st.toggle(
            t("cfg_agent_toggle").format(name="market_regime"),
            mr_cfg.get("enabled", True),
            key="toggle_market_regime"
        )
        st.caption(t("cfg_regime_agent_note"))
        agents["market_regime"] = mr_cfg

        # AlphaCombination — pondération dynamique IC-based
        st.markdown("---")
        st.markdown("**⚗ Alpha Combination** *(Fundamental Law of Active Management)*")
        ac_cfg = agents.get("alpha_combination", {})
        col1, col2 = st.columns([2, 1])
        with col1:
            ac_cfg["enabled"] = st.toggle(
                "Poids dynamiques IC-based (remplace weight_in_scoring statiques)",
                ac_cfg.get("enabled", False),
                key="toggle_alpha_combination",
                help="Active la pondération dynamique des agents basée sur leur Information Coefficient historique. Nécessite min_history trades évalués.",
            )
        with col2:
            ac_cfg["min_history"] = st.number_input(
                "Min trades évalués", 5, 200,
                int(ac_cfg.get("min_history", 20)), 5,
                key="ac_min_history",
                help="Nombre minimum de trades avec result_24h pour activer les poids dynamiques."
            )
        col3, col4 = st.columns(2)
        with col3:
            ac_cfg["lookback_days"] = st.number_input(
                "Fenêtre (jours)", 7, 365,
                int(ac_cfg.get("lookback_days", 90)), 7,
                key="ac_lookback_days",
            )
        with col4:
            ac_cfg["ic_floor"] = st.number_input(
                "IC floor (seuil min)", 0.0, 0.5,
                float(ac_cfg.get("ic_floor", 0.0)), 0.01,
                key="ac_ic_floor",
                help="Les agents avec IC ≤ ce seuil reçoivent un poids nul.",
            )
        if ac_cfg.get("enabled"):
            st.info("Actif : les poids seront recalculés à chaque cycle selon l'historique des 20+ derniers trades évalués.")
        else:
            st.caption("Inactif — poids statiques weight_in_scoring utilisés.")
        agents["alpha_combination"] = ac_cfg

        settings["agents"] = agents

    with sub_tabs[7]:  # Logging
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

    with sub_tabs[8]:  # TimesFM
        st.markdown(f'<h4><i class="fas fa-chart-line" style="margin-right:7px;color:#7986cb;"></i>{t("cfg_timesfm_title")}</h4>', unsafe_allow_html=True)
        st.info(t("cfg_timesfm_info"))
        tfm = settings.get("timesfm", {})
        tfm["forecast_horizon"] = st.number_input(
            t("cfg_tfm_horizon"), 1, 96,
            int(tfm.get("forecast_horizon", 24)), 1,
            help=t("cfg_tfm_horizon_help")
        )
        settings["timesfm"] = tfm

        # ── Performance TimesFM ──
        st.markdown("---")
        st.markdown(f'<h4><i class="fas fa-bullseye" style="margin-right:7px;color:#7986cb;"></i>{t("cfg_tfm_perf_title")}</h4>', unsafe_allow_html=True)
        try:
            from storage.database import get_timesfm_stats, evaluate_timesfm_forecasts
            # Évaluer les forecasts arrivés à échéance
            n_eval = evaluate_timesfm_forecasts()
            if n_eval:
                st.toast(f"{n_eval} forecast(s) evaluated", icon="🎯")

            stats = get_timesfm_stats()

            if stats["total"] == 0:
                st.info(t("cfg_tfm_no_data"))
            else:
                theme = _get_theme()
                bg, bdr, txt, muted, ic = _card_colors(theme)
                kw = dict(bg=bg, bdr=bdr, txt=txt, muted=muted, ic=ic)

                dir_acc = f"{stats['direction_accuracy']:.0f}%" if stats["direction_accuracy"] is not None else "—"
                mae_val = f"{stats['mae']:.2f}%" if stats["mae"] is not None else "—"
                lat_val = f"{stats['avg_latency_ms']}ms" if stats["avg_latency_ms"] else "—"
                conf_val = f"{stats['avg_confidence']:.0%}" if stats["avg_confidence"] is not None else "—"

                grid = (
                    _html_card("fas fa-chart-simple", t("cfg_tfm_total"), str(stats["total"]), **kw) +
                    _html_card("fas fa-check-double", t("cfg_tfm_evaluated"), str(stats["evaluated"]), **kw) +
                    _html_card("fas fa-bullseye", t("cfg_tfm_dir_acc"), dir_acc, **kw) +
                    _html_card("fas fa-ruler", t("cfg_tfm_mae"), mae_val, **kw) +
                    _html_card("fas fa-gauge", t("cfg_tfm_confidence"), conf_val, **kw) +
                    _html_card("fas fa-bolt", t("cfg_tfm_latency"), lat_val, **kw)
                )
                st.markdown(
                    f'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));'
                    f'gap:10px;margin-bottom:16px;">{grid}</div>',
                    unsafe_allow_html=True,
                )

                # Tableau — dernières prédictions évaluées
                if stats.get("recent"):
                    st.markdown(f"**{t('cfg_tfm_recent')}**")
                    for r in stats["recent"]:
                        hit = "✅" if r["direction_hit"] else "❌"
                        sig_icon = {"BULLISH": "🟢", "BEARISH": "🔴"}.get(r.get("signal", ""), "⚪")
                        st.markdown(
                            f"{hit} {sig_icon} `{r['timestamp'][:16]}` — "
                            f"Pred: **{r['pct_change']:+.2f}%** → Real: **{r['actual_change']:+.2f}%** "
                            f"(${r['current_price']:,.0f} → ${r['actual_price']:,.0f})"
                        )

                # Prédictions en attente
                if stats.get("pending"):
                    st.markdown(f"**{t('cfg_tfm_pending')}**")
                    for p in stats["pending"]:
                        sig_icon = {"BULLISH": "🟢", "BEARISH": "🔴"}.get(p.get("signal", ""), "⚪")
                        st.markdown(
                            f"⏳ {sig_icon} `{p['timestamp'][:16]}` — "
                            f"Pred: **{p['pct_change']:+.2f}%** "
                            f"(${p['current_price']:,.0f} → ${p['predicted_price']:,.0f}) "
                            f"horizon: {p['horizon_candles']}×15min"
                        )
        except Exception as exc:
            st.warning(f"TimesFM stats unavailable: {exc}")

    with sub_tabs[9]:  # Agents Perf
        st.markdown('<h4>📊 Performance par agent</h4>', unsafe_allow_html=True)
        st.caption(
            "Win rate, Brier score et P&L moyen par agent individuel sur les décisions évaluées. "
            "Win rate > 55% = signal utile. Brier < 0.22 = meilleur que le hasard."
        )
        try:
            from storage.database import get_agent_performance_stats
            _ap_all_assets = list(settings.get("project", {}).get("active_assets", []))
            _ap_c1, _ap_c2 = st.columns(2)
            with _ap_c1:
                _ap_asset_sel = st.radio(
                    "Actif", ["Tous"] + _ap_all_assets,
                    horizontal=True, key="ap_asset_sel"
                )
            with _ap_c2:
                _ap_days = st.radio(
                    "Fenêtre (jours)", [7, 14, 30, 60, 90],
                    index=2, horizontal=True, key="ap_days"
                )
            _ap_asset = None if _ap_asset_sel == "Tous" else _ap_asset_sel
            _ap_stats = get_agent_performance_stats(asset=_ap_asset, days=_ap_days)

            if not _ap_stats:
                st.info("Pas encore assez de décisions évaluées (min 5 par agent).")
            else:
                # Tableau HTML
                def _wr_color(wr):
                    if wr >= 60: return "#27ae60"
                    if wr >= 50: return "#f39c12"
                    return "#e74c3c"

                def _brier_color(b):
                    if b < 0.20: return "#27ae60"
                    if b < 0.24: return "#f39c12"
                    return "#e74c3c"

                _ap_rows = ""
                for _ap in _ap_stats:
                    _wrc = _wr_color(_ap["win_rate"])
                    _bc  = _brier_color(_ap["brier_score"])
                    _pnl_color = "#27ae60" if _ap["avg_pnl_on_buy"] >= 0 else "#e74c3c"
                    _wt = f"{_ap['current_weight']:.2f}" if _ap["current_weight"] is not None else "–"
                    _ap_rows += (
                        f"<tr>"
                        f"<td style='padding:5px 10px;'><b>{_ap['agent']}</b></td>"
                        f"<td style='padding:5px 10px;color:{_wrc};font-weight:bold;'>{_ap['win_rate']}%</td>"
                        f"<td style='padding:5px 10px;'>{_ap['signal_count']}</td>"
                        f"<td style='padding:5px 10px;'>{_ap['avg_score']:.0f}</td>"
                        f"<td style='padding:5px 10px;color:{_bc};'>{_ap['brier_score']:.4f}</td>"
                        f"<td style='padding:5px 10px;color:{_pnl_color};'>{_ap['avg_pnl_on_buy']:+.2f}$</td>"
                        f"<td style='padding:5px 10px;opacity:.7;'>{_wt}</td>"
                        f"</tr>"
                    )
                st.markdown(
                    f"""<table style='width:100%;border-collapse:collapse;'>
                    <thead><tr style='border-bottom:1px solid #444;font-size:11px;opacity:.6;'>
                      <th style='padding:4px 10px;text-align:left;'>Agent</th>
                      <th style='padding:4px 10px;text-align:left;'>Win Rate</th>
                      <th style='padding:4px 10px;text-align:left;'>Signaux</th>
                      <th style='padding:4px 10px;text-align:left;'>Score moy.</th>
                      <th style='padding:4px 10px;text-align:left;'>Brier ↓</th>
                      <th style='padding:4px 10px;text-align:left;'>P&L moy/BUY</th>
                      <th style='padding:4px 10px;text-align:left;'>Poids actuel</th>
                    </tr></thead>
                    <tbody>{_ap_rows}</tbody>
                    </table>""",
                    unsafe_allow_html=True,
                )
                st.markdown("---")
                st.caption(
                    "🟢 Win rate ≥ 60% → signal fiable | "
                    "🟡 50-60% → signal marginalement utile | "
                    "🔴 < 50% → signal néfaste, envisager de désactiver"
                )
        except Exception as _ap_exc:
            st.warning(f"Stats agents indisponibles : {_ap_exc}")

    with sub_tabs[10]:  # Méta-Analyse
        st.markdown('<h4>🔍 Méta-Analyse LLM — Patterns d\'échec</h4>', unsafe_allow_html=True)
        st.caption(
            "Claude analyse les décisions perdantes pour détecter des patterns récurrents, "
            "identifier les agents peu fiables et formuler des recommandations concrètes."
        )
        try:
            from storage.database import get_last_meta_analysis, get_decisions_for_meta
            import json as _ma_json

            _ma_analyses = get_last_meta_analysis(limit=3)

            _ma_days_sel = st.radio(
                "Fenêtre d'analyse (jours)", [14, 30, 60, 90],
                index=1, horizontal=True, key="ma_days"
            )
            if st.button("▶ Lancer une méta-analyse maintenant", key="btn_run_meta"):
                try:
                    from agents.post_mortem_agent import PostMortemAgent as _PMA
                    with st.spinner("Analyse en cours (30–90s)..."):
                        _PMA().run_meta_analysis_now()
                    st.success("Analyse terminée — rechargez la page")
                    st.rerun()
                except Exception as _ma_btn_exc:
                    st.error(f"Erreur : {_ma_btn_exc}")

            if not _ma_analyses:
                _ma_trades = get_decisions_for_meta(days=_ma_days_sel)
                _ma_losing = [t for t in _ma_trades if t["result"] < 0]
                st.info(
                    f"Aucune méta-analyse disponible. "
                    f"{len(_ma_losing)} trades perdants sur {_ma_days_sel}j. "
                    f"Cliquez ▶ pour lancer une analyse (nécessite ≥5 pertes)."
                )
            else:
                for _ma_idx, _ma_item in enumerate(_ma_analyses):
                    _ma_ts = _ma_item.get("timestamp", "")[:16]
                    _ma_n  = _ma_item.get("n_trades", 0)
                    _ma_nl = _ma_item.get("n_losing", 0)
                    _ma_trig = _ma_item.get("run_trigger", "auto")

                    with st.expander(
                        f"{'🕐' if _ma_idx > 0 else '🔍'} Analyse du {_ma_ts} UTC — "
                        f"{_ma_nl} pertes / {_ma_n} trades ({_ma_trig})",
                        expanded=(_ma_idx == 0),
                    ):
                        # Afficher les recommandations structurées si JSON disponible
                        if _ma_item.get("patterns_json"):
                            try:
                                _ma_data = _ma_json.loads(_ma_item["patterns_json"])

                                _ma_resume = _ma_data.get("resume", "")
                                if _ma_resume:
                                    st.info(_ma_resume)

                                _ma_recos = _ma_data.get("recos", [])
                                if _ma_recos:
                                    st.markdown("**✅ Recommandations :**")
                                    for _r in sorted(_ma_recos, key=lambda x: x.get("priorite", 99)):
                                        st.markdown(
                                            f"{_r.get('priorite','?')}. **{_r.get('action','?')}**  "
                                            f"→ *{_r.get('rationale','')}*"
                                        )

                                _ma_ags = _ma_data.get("agents_problematiques", [])
                                if _ma_ags:
                                    st.markdown("**⚠️ Agents problématiques :**")
                                    for _ag in _ma_ags:
                                        st.markdown(
                                            f"- **{_ag.get('agent','?')}** : {_ag.get('probleme','?')}  "
                                            f"  ↳ *{_ag.get('condition','')}*"
                                        )

                                _ma_patterns = _ma_data.get("patterns", [])
                                if _ma_patterns:
                                    st.markdown("**🔴 Patterns récurrents :**")
                                    for _p in _ma_patterns:
                                        _imp = _p.get("impact", "")
                                        _ic = "🔴" if _imp == "fort" else ("🟡" if _imp == "moyen" else "🟢")
                                        st.markdown(
                                            f"- {_ic} {_p.get('pattern','?')} "
                                            f"*(fréquence: {_p.get('frequence','?')})*"
                                        )

                                _ma_pos = _ma_data.get("points_positifs", "")
                                if _ma_pos:
                                    st.markdown(f"**💚 Points positifs :** {_ma_pos}")
                            except Exception:
                                st.markdown(_ma_item.get("summary_text", ""))
                        else:
                            st.markdown(_ma_item.get("summary_text", "_Aucun contenu_"))

        except Exception as _ma_exc:
            st.warning(f"Méta-analyse indisponible : {_ma_exc}")

    with sub_tabs[11]:  # Market Regime
        st.markdown(f'<h4><i class="fas fa-wave-square" style="margin-right:7px;color:#7986cb;"></i>{t("cfg_regime_title")}</h4>', unsafe_allow_html=True)
        st.info(t("cfg_regime_info"))

        # --- Régime par actif (lecture DB) ---
        try:
            from storage.database import get_recent_decisions
            import json as _json

            _regime_assets = list(settings.get("project", {}).get("active_assets",
                                  ["BTC/USDT", "ETH/USDT", "XAU/USD", "EUR/USD", "GBP/USD"]))
            _regime_icons  = {"BTC/USDT": "₿", "ETH/USDT": "⟠", "XAU/USD": "◎", "EUR/USD": "€", "GBP/USD": "£"}
            _badge_colors  = {"TRENDING_UP": "#43a047", "TRENDING_DOWN": "#e53935",
                               "SIDEWAYS": "#fb8c00", "HIGH_VOLATILITY": "#e65100"}
            _regime_emojis = {"TRENDING_UP": "▲", "TRENDING_DOWN": "▼",
                               "SIDEWAYS": "↔", "HIGH_VOLATILITY": "⚡"}

            _rcols = st.columns(len(_regime_assets))
            for _ri, _ra in enumerate(_regime_assets):
                with _rcols[_ri]:
                    _rdecs = get_recent_decisions(6, asset=_ra)
                    if not _rdecs:
                        st.caption(f"{_regime_icons.get(_ra,'◆')} **{_ra.split('/')[0]}**\n\n_Aucune donnée_")
                        continue
                    _rws   = _json.loads(_rdecs[0].get("weights_snapshot") or "{}")
                    _rn    = _rws.get("regime", "UNKNOWN")
                    _rp    = float(_rws.get("hmm_prob", 0.5))
                    _rfeat = _rws.get("regime_features", {})
                    _rdir  = _rws.get("direction_pressure", "")
                    _rpost = _rws.get("hmm_posteriors", {})
                    _rts   = _rdecs[0].get("timestamp", "?")
                    _rcolor = _badge_colors.get(_rn, "#757575")
                    _rem   = _regime_emojis.get(_rn, "?")
                    # ADX + DI
                    _adx = _rfeat.get("adx", 0)
                    _adx_str = f'ADX {_adx:.1f}'
                    if "di_plus" in _rfeat:
                        _adx_str += f' (DI+{_rfeat["di_plus"]:.1f}/DI−{_rfeat["di_minus"]:.1f})'
                    # Vol
                    _vol = _rfeat.get("rel_volatility", 0)
                    _vol_str = f'Vol {_vol:.2f}×'
                    if "vol_abs_annualized" in _rfeat:
                        _vol_str += f' ({_rfeat["vol_abs_annualized"]:.0f}%)'
                    # HMM posteriors
                    _post_str = ""
                    if _rpost:
                        _plabels = {0: "Low-vol", 1: "High-vol"}
                        _pparts = [f'{_plabels.get(int(k.split("_")[-1]), k)}: {v:.0%}'
                                   for k, v in sorted(_rpost.items())]
                        _post_str = " | ".join(_pparts)
                    # Historique 5 cycles
                    _rhist = []
                    for _rd in _rdecs[1:6]:
                        _rws2 = _json.loads(_rd.get("weights_snapshot") or "{}")
                        _r2 = _rws2.get("regime", "")
                        _p2 = float(_rws2.get("hmm_prob", 0.5))
                        if _r2:
                            _c2 = _badge_colors.get(_r2, "#757575")
                            _e2 = _regime_emojis.get(_r2, "?")
                            _rhist.append(f'<span style="color:{_c2};font-size:0.72rem">{_e2} {_r2} ({_p2:.0%})</span>')
                    _rhist_str = " ← ".join(_rhist) if _rhist else ""
                    # Timestamp court
                    _rts_short = str(_rts)[:16] if _rts else ""
                    st.markdown(
                        f'<div style="border:1px solid {_rcolor};border-radius:7px;'
                        f'padding:8px 10px;background:rgba(0,0,0,0.18);margin-bottom:4px">'
                        f'<div style="font-size:0.82rem;color:#aaa">'
                        f'{_regime_icons.get(_ra,"◆")} <b>{_ra.split("/")[0]}</b></div>'
                        f'<div style="font-size:1.05rem;font-weight:700;color:{_rcolor}">'
                        f'{_rem} {_rn}'
                        + (f' <span style="font-size:0.78rem;font-weight:400;color:#b0bec5">{_rdir}</span>'
                           if _rdir else "")
                        + f'</div>'
                        f'<div style="font-size:0.75rem;color:#ccc;margin-top:2px">HMM {_rp:.0%} · {_adx_str}</div>'
                        f'<div style="font-size:0.75rem;color:#ccc">{_vol_str}</div>'
                        + (f'<div style="font-size:0.72rem;color:#90a4ae;margin-top:2px">{_post_str}</div>'
                           if _post_str else "")
                        + (f'<div style="margin-top:3px">{_rhist_str}</div>' if _rhist_str else "")
                        + (f'<div style="color:#ef9a9a;font-size:0.72rem;margin-top:2px">'
                           f'⚠ HIGH VOL : pos ×0.65 · CB 0.035%</div>'
                           if _rn == "HIGH_VOLATILITY" else "")
                        + f'<div style="color:#546e7a;font-size:0.70rem;margin-top:2px">{_rts_short}</div>'
                        + '</div>',
                        unsafe_allow_html=True
                    )
        except Exception:
            st.caption(t("cfg_regime_no_data"))

        st.caption("💡 Les paramètres HMM, ADX, fenêtres vol/trend sont configurables **par actif** dans l'onglet **🎯 Par Actif**.")

    with sub_tabs[12]:  # Flux Manager
        st.info(t("cfg_flux_info"))
        render_flux_manager_page()
        # pas de bouton save ici, géré dans flux_manager

    with sub_tabs[13]:  # Utilisateurs
        st.info(t("cfg_users_info"))
        from dashboard.auth import render_users_admin
        render_users_admin()
        # sauvegarde gérée dans render_users_admin

    with sub_tabs[14]:  # Par Actif — config/assets/{slug}.yaml
        st.markdown(
            '<h4><i class="fas fa-layer-group" style="margin-right:7px;color:#7986cb;"></i>'
            'Configuration par actif</h4>',
            unsafe_allow_html=True,
        )
        st.info(
            "Les paramètres ci-dessous surchargent les valeurs globales pour chaque actif. "
            "Fichiers : config/assets/{SLUG}.yaml — cliquez 💾 pour valider chaque actif séparément."
        )

        # ── Actifs surveillés (anciennement onglet Marchés) ───────────────────
        st.markdown("""<style>
[data-testid="stMultiSelect"] span[data-baseweb="tag"] {
    min-width:90px!important;max-width:none!important;
    padding-left:10px!important;padding-right:10px!important;
}
[data-testid="stMultiSelect"] span[data-baseweb="tag"] span:first-child {
    overflow:visible!important;white-space:nowrap!important;text-overflow:unset!important;
}
</style>""", unsafe_allow_html=True)
        # Découverte dynamique depuis les fichiers config/assets/*.yaml
        try:
            from pathlib import Path as _PKPath
            _pk_dir = _PKPath(__file__).parent.parent / "config" / "assets"
            _pa_known = sorted([
                p.stem.replace("_", "/", 1)
                for p in _pk_dir.glob("*.yaml")
            ])
        except Exception:
            _pa_known = ["BTC/USDT", "ETH/USDT", "XAU/USD", "EUR/USD", "GBP/USD"]
        _pa_current_active = list(settings.get("project", {}).get("active_assets", _pa_known))
        # S'assurer que tous les actifs actifs sont dans les options
        _pa_options = sorted(set(_pa_known) | set(_pa_current_active))
        _pa_new_active = st.multiselect(
            "🌐 Actifs surveillés",
            options=_pa_options,
            default=_pa_current_active,
            help="Seuls les actifs ayant un fichier config/assets/*.yaml sont supportés.",
            key="pa_active_assets",
        )
        if st.button("💾 Sauvegarder la liste des actifs", key="btn_save_active_assets"):
            try:
                settings.setdefault("project", {})["active_assets"] = _pa_new_active
                if _save_settings(settings):
                    st.success(f"Liste sauvegardée : {', '.join(_pa_new_active)}")
                else:
                    st.error("Erreur sauvegarde settings.yaml")
            except Exception as _exc_aa:
                st.error(f"Erreur : {_exc_aa}")
        _pa_all = _pa_new_active or _pa_current_active

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

                # ── Général ──────────────────────────────────────────────────
                with st.expander("⚙ Général", expanded=True):
                    _c1, _c2 = st.columns(2)
                    with _c1:
                        _pacfg["paper_capital_usd"] = st.number_input(
                            "Capital paper (USD)", 1000, 1_000_000,
                            int(_pacfg.get("paper_capital_usd", 10000)), step=500,
                            key=f"pa_cap_{_paslug}"
                        )
                        _pacfg["loop_interval_seconds"] = st.number_input(
                            "Intervalle boucle (s)", 60, 3600,
                            int(_pacfg.get("loop_interval_seconds", 900)), step=60,
                            key=f"pa_loop_{_paslug}"
                        )
                    with _c2:
                        _pamon = dict(_pacfg.get("monitor", {}))
                        _pamon["interval_seconds"] = st.number_input(
                            "Monitor interval (s)", 30, 600,
                            int(_pamon.get("interval_seconds", 60)), step=10,
                            key=f"pa_mon_{_paslug}"
                        )
                        _pamon["breaking_news_threshold"] = st.slider(
                            "Breaking news seuil", 0.4, 0.9,
                            float(_pamon.get("breaking_news_threshold", 0.65)), 0.05,
                            key=f"pa_bnt_{_paslug}"
                        )
                        _pacfg["monitor"] = _pamon

                # ── Risk & Seuils ─────────────────────────────────────────────
                with st.expander("⚖ Risk & Seuils", expanded=True):
                    _par = dict(_pacfg.get("risk", {}))
                    _c1, _c2 = st.columns(2)
                    with _c1:
                        _rmodes_pa = ["conservative", "balanced", "aggressive"]
                        _rdef_pa = _par.get("mode", "balanced")
                        if _rdef_pa not in _rmodes_pa:
                            _rmodes_pa.append(_rdef_pa)
                        _par["mode"] = st.radio(
                            "Mode", _rmodes_pa, index=_rmodes_pa.index(_rdef_pa),
                            horizontal=True, key=f"pa_rmode_{_paslug}"
                        )
                        _par["buy_threshold"] = st.slider(
                            "Seuil BUY", 50, 95, int(_par.get("buy_threshold", 62)),
                            key=f"pa_buy_{_paslug}"
                        )
                        _par["exit_threshold"] = st.slider(
                            "Seuil EXIT", 20, 60, int(_par.get("exit_threshold", 52)),
                            key=f"pa_exit_{_paslug}"
                        )
                        _par["kelly_max_fraction"] = st.slider(
                            "Kelly max", 0.05, 0.50,
                            float(_par.get("kelly_max_fraction", 0.25)), 0.05,
                            key=f"pa_kelly_{_paslug}"
                        )
                        _par["position_size_pct"] = st.slider(
                            "Position size (%)", 0.5, 20.0,
                            float(_par.get("position_size_pct", 5.0)), 0.5,
                            key=f"pa_pos_{_paslug}"
                        )
                    with _c2:
                        _par["max_drawdown_pct"] = st.slider(
                            "Max drawdown (%)", 3.0, 50.0,
                            float(_par.get("max_drawdown_pct", 15.0)), 1.0,
                            key=f"pa_dd_{_paslug}"
                        )
                        _par["max_open_positions"] = st.number_input(
                            "Max positions", 1, 20,
                            int(_par.get("max_open_positions", 3)),
                            key=f"pa_mop_{_paslug}"
                        )
                        _par["atr_multiplier_sl"] = st.slider(
                            "ATR ×SL", 0.5, 5.0,
                            float(_par.get("atr_multiplier_sl", 2.0)), 0.25,
                            key=f"pa_atrs_{_paslug}"
                        )
                        _par["atr_multiplier_tp"] = st.slider(
                            "ATR ×TP", 0.5, 8.0,
                            float(_par.get("atr_multiplier_tp", 3.0)), 0.25,
                            key=f"pa_atrtp_{_paslug}"
                        )
                        _par["human_in_the_loop"] = st.toggle(
                            "Human in the loop",
                            _par.get("human_in_the_loop", False),
                            key=f"pa_hitl_{_paslug}"
                        )
                    st.markdown("**📊 Filtre MA50**")
                    _ma50_opts_pa = ["off", "gradual", "block", "strict"]
                    _ma50_def_pa = _par.get("ma50_filter_mode", "gradual")
                    if _ma50_def_pa not in _ma50_opts_pa:
                        _ma50_opts_pa.append(_ma50_def_pa)
                    _par["ma50_filter_mode"] = st.radio(
                        "Mode MA50", _ma50_opts_pa,
                        index=_ma50_opts_pa.index(_ma50_def_pa),
                        horizontal=True, key=f"pa_ma50mode_{_paslug}"
                    )
                    if _par["ma50_filter_mode"] == "gradual":
                        _cm1, _cm2 = st.columns(2)
                        _par["ma50_strong_signal_threshold"] = _cm1.slider(
                            "Score min fort", 60, 95,
                            int(_par.get("ma50_strong_signal_threshold", 72)),
                            key=f"pa_ma50s_{_paslug}"
                        )
                        _par["ma50_gradual_size_factor"] = _cm2.slider(
                            "Taille réduite ×", 0.1, 1.0,
                            float(_par.get("ma50_gradual_size_factor", 0.5)), 0.05,
                            key=f"pa_ma50f_{_paslug}"
                        )
                    _pacfg["risk"] = _par

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
                                "Max réduction", 0.0, 1.0,
                                float(_pcb.get("max_reduction", 0.75)), 0.05,
                                key=f"pa_cbmr_{_paslug}"
                            )
                        _pacfg["circuit_breaker"] = _pcb

                # ── Scoring ───────────────────────────────────────────────────
                with st.expander("🎯 Scoring — Poids des composantes", expanded=False):
                    _psc = dict(_pacfg.get("scoring", {}))
                    _pw = dict(_psc.get("weights", {}))
                    _c1, _c2 = st.columns(2)
                    with _c1:
                        _pw["mirofish"] = st.slider(
                            "MiroFish", 0.0, 0.5,
                            float(_pw.get("mirofish", 0.12)), 0.01, key=f"pa_wmf_{_paslug}"
                        )
                        _pw["market"] = st.slider(
                            "Market Data", 0.0, 0.8,
                            float(_pw.get("market", 0.40)), 0.01, key=f"pa_wmd_{_paslug}"
                        )
                    with _c2:
                        _pw["agents"] = st.slider(
                            "Agents", 0.0, 0.8,
                            float(_pw.get("agents", 0.30)), 0.01, key=f"pa_wag_{_paslug}"
                        )
                        _pw["contrarian"] = st.slider(
                            "Contrarian", 0.0, 0.5,
                            float(_pw.get("contrarian", 0.18)), 0.01, key=f"pa_wco_{_paslug}"
                        )
                    _ptot = sum(_pw.values())
                    if abs(_ptot - 1.0) > 0.05:
                        st.warning(f"⚠ Total poids : {_ptot:.2f} (idéalement = 1.0)")
                    else:
                        st.caption(f"Total poids : {_ptot:.2f} ✓")
                    _psc["weights"] = _pw
                    _pacfg["scoring"] = _psc

                # ── Agents activés ────────────────────────────────────────────
                with st.expander("⬡ Agents activés", expanded=False):
                    _pags = dict(_pacfg.get("agents", {}))
                    _ag_list = [
                        "market_data", "fundamental", "x_sentiment", "contrarian",
                        "fear_greed", "polymarket", "timesfm", "market_regime",
                    ]
                    if _is_forex_pa or _is_commodity_pa:
                        _ag_list.append("economic_calendar")
                    if _is_forex_pa:
                        _ag_list.append("central_bank")
                    for _agn in _ag_list:
                        _agc = dict(_pags.get(_agn, {}))
                        _agc["enabled"] = st.toggle(
                            _agn.replace("_", " ").title(),
                            _agc.get("enabled", True),
                            key=f"pa_agen_{_paslug}_{_agn}"
                        )
                        if _agn == "x_sentiment":
                            _xkw = ", ".join(_agc.get("keywords", []))
                            _nkw = st.text_input(
                                "Keywords X/Twitter", value=_xkw,
                                key=f"pa_xkw_{_paslug}"
                            )
                            _agc["keywords"] = [k.strip() for k in _nkw.split(",") if k.strip()]
                        _pags[_agn] = _agc
                    _pacfg["agents"] = _pags

                # ── Market Regime ─────────────────────────────────────────────
                with st.expander("⊞ Market Regime", expanded=False):
                    _pmr = dict(_pacfg.get("market_regime", {}))
                    _c1, _c2 = st.columns(2)
                    with _c1:
                        _pmr["n_hmm_states"] = st.number_input(
                            "N états HMM", 2, 4, int(_pmr.get("n_hmm_states", 2)),
                            key=f"pa_hmm_{_paslug}"
                        )
                        _pmr["adx_period"] = st.slider(
                            "Période ADX", 7, 30, int(_pmr.get("adx_period", 18)),
                            key=f"pa_adx_{_paslug}"
                        )
                    with _c2:
                        _pmr["vol_window"] = st.slider(
                            "Fenêtre vol.", 10, 60, int(_pmr.get("vol_window", 30)),
                            key=f"pa_vw_{_paslug}"
                        )
                        _pmr["trend_window"] = st.slider(
                            "Fenêtre trend", 20, 100, int(_pmr.get("trend_window", 50)),
                            key=f"pa_tw_{_paslug}"
                        )
                    _pacfg["market_regime"] = _pmr

                # ── MiroFish poids ────────────────────────────────────────────
                with st.expander("🐟 MiroFish — Poids par actif", expanded=False):
                    _pmf = dict(_pacfg.get("mirofish", {}))
                    _mf_global = settings.get("mirofish", {})
                    _mf_news_default = float(_pmf.get("seed_news_weight",
                                             _mf_global.get("seed_news_weight", 0.6)))
                    _mf_news_new = st.slider(
                        "Poids News récentes",
                        0.0, 1.0, _mf_news_default, 0.05,
                        key=f"pa_mf_news_{_paslug}",
                        help="Part des news récentes dans le seed MiroFish. "
                             "Crypto : news-driven → ~0.7. Forex/Or : macro-driven → ~0.4."
                    )
                    _pmf["seed_news_weight"] = round(_mf_news_new, 2)
                    _pmf["air_du_temps_weight"] = round(1.0 - _mf_news_new, 2)
                    st.metric("Poids Air du Temps", f"{_pmf['air_du_temps_weight']:.0%}")
                    _pacfg["mirofish"] = _pmf

                # ── Crawler templates ─────────────────────────────────────────
                with st.expander("⛏ Templates Crawler", expanded=False):
                    _pcr = dict(_pacfg.get("crawler", {}))
                    _pcr_raw = "\n".join(_pcr.get("templates", []))
                    _pcr_new = st.text_area(
                        f"Templates spécifiques {_pas} (un par ligne)",
                        value=_pcr_raw, height=200,
                        key=f"pa_crawler_{_paslug}",
                        help="{asset} → ticker court (ex: BTC), {year} → année courante. "
                             "Les templates macro globaux (onglet Crawler) sont toujours ajoutés."
                    )
                    _pcr["templates"] = [
                        l.strip() for l in _pcr_new.splitlines()
                        if l.strip() and not l.strip().startswith("#")
                    ]
                    st.caption(f"{len(_pcr['templates'])} templates spécifiques + templates macro globaux")
                    _pacfg["crawler"] = _pcr

                # ── Bouton Sauvegarder ────────────────────────────────────────
                st.markdown("---")
                if st.button(
                    f"💾 Sauvegarder {_pas}",
                    key=f"pa_save_{_paslug}",
                    type="primary",
                    use_container_width=True,
                ):
                    try:
                        from utils.config import save_asset_config as _sac
                        _padir.mkdir(parents=True, exist_ok=True)
                        _sac(_pas, _pacfg)
                        st.success(f"✅ config/assets/{_paslug}.yaml sauvegardé")
                    except Exception as _savexc:
                        st.error(f"❌ Erreur sauvegarde : {_savexc}")

    # Bouton de sauvegarde (pour tous les onglets sauf Flux Manager et Par Actif)
    st.markdown("---")
    if st.button(t('save_config_btn'), type="primary", use_container_width=True):
        if _save_settings(settings):
            st.success(f"✅ {t('config_saved')}")
        else:
            st.error(f"❌ {t('config_error')}")


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
                col_dec, col_chart = st.columns([1, 1], gap="medium")
                with col_dec:
                    render_last_decision(_lc)
                with col_chart:
                    render_agent_scores_chart(asset)
                render_trades_list(_tr)
                render_pnl_chart(_tr, key=f"pnl_chart_{asset.replace('/', '_')}")
                render_live_chart(asset)
                render_live_logs(key=asset.replace('/', '_'))

            def _render_portfolio_first():
                """Portefeuille global — affiché en tête de la vue Global."""
                render_portfolio(portfolio)

            def _render_global():
                """Vue consolidée : PnL tous actifs + profils + logs."""
                _tr_all = _get_recent_trades(500)
                render_trades_list_sortable(_tr_all)
                render_pnl_chart(_tr_all, key="pnl_chart_global")
                render_profile_comparison()
                render_live_logs(key="global")

            render_asset_tabs(_render_for_asset, global_fn=_render_global, pre_global_fn=_render_portfolio_first)
            st.markdown(
                '<div style="text-align:center;padding:24px 0 8px;'
                'font-size:11px;opacity:0.35;">Atlas Trader &mdash; by Jako 2026</div>',
                unsafe_allow_html=True,
            )

if __name__ == "__main__":
    main()
