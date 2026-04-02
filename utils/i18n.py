"""
utils/i18n.py — Internationalisation minimale (FR / EN)
Usage :
    from utils.i18n import t
    st.subheader(t("climate_title"))
"""
from __future__ import annotations

_TRANSLATIONS: dict[str, dict[str, str]] = {
    # Dashboard sections
    "climate_title":        {"fr": "Climat de marché",             "en": "Market Climate"},
    "portfolio_title":      {"fr": "Portefeuille",                  "en": "Portfolio"},
    "last_decision_title":  {"fr": "Dernière décision IA",          "en": "Latest AI Decision"},
    "btc_live_title":       {"fr": "BTC Live — Positions ouvertes",  "en": "BTC Live — Open Positions"},
    "perf_chart_title":     {"fr": "Performance cumulée",           "en": "Cumulative Performance"},
    "trades_title":         {"fr": "Historique des trades",         "en": "Trade History"},
    "logs_title":           {"fr": "Logs temps réel",               "en": "Real-time Logs"},
    "admin_title":          {"fr": "Accès Administration",          "en": "Admin Access"},
    # Metrics
    "score_label":          {"fr": "Score de conviction",        "en": "Conviction Score"},
    "last_decision_label":  {"fr": "Dernière décision",            "en": "Last Decision"},
    "last_cycle_label":     {"fr": "Dernier cycle",               "en": "Last Cycle"},
    "total_trades_label":   {"fr": "Total trades",                "en": "Total Trades"},
    "ma50_label":           {"fr": "Tendance MA50",               "en": "MA50 Trend"},
    "ma50_bull":            {"fr": "Haussier",                    "en": "Bullish"},
    "ma50_bear":            {"fr": "Baissier",                    "en": "Bearish"},
    "buy_blocked":          {"fr": "BUY bloqué",                  "en": "BUY blocked"},
    "capital_label":        {"fr": "Capital initial",             "en": "Initial Capital"},
    "value_label":          {"fr": "Valeur actuelle",             "en": "Current Value"},
    "pnl_label":            {"fr": "P&L total",                   "en": "Total P&L"},
    "trades_label":         {"fr": "Trades exécutés",             "en": "Executed Trades"},
    "open_pos_label":       {"fr": "Positions ouvertes",          "en": "Open Positions"},
    "btc_price_label":      {"fr": "Prix BTC actuel",             "en": "Current BTC Price"},
    # Table columns
    "col_date":             {"fr": "Date",                        "en": "Date"},
    "col_action":           {"fr": "Action",                      "en": "Action"},
    "col_price":            {"fr": "Prix entrée",                 "en": "Entry Price"},
    "col_entry":            {"fr": "Prix entrée",                 "en": "Entry Price"},
    "col_size":             {"fr": "Taille ($)",                  "en": "Size ($)"},
    "col_sl":               {"fr": "SL",                          "en": "SL"},
    "col_tp":               {"fr": "TP",                          "en": "TP"},
    "col_pnl":              {"fr": "P&L 24h",                     "en": "P&L 24h"},
    "col_score":            {"fr": "Score",                       "en": "Score"},
    # Status
    "pending":              {"fr": "⏳ en cours",                 "en": "⏳ pending"},
    "no_trades":            {"fr": "Aucun trade exécuté pour l'instant.", "en": "No trades executed yet."},
    "no_cycle":             {"fr": "Aucun cycle exécuté. Cliquez sur 'Force Run' pour démarrer.",
                             "en": "No cycle run yet. Click 'Force Run' to start."},
    "no_perf_data":         {"fr": "Pas encore de trades avec résultats. Les données apparaîtront après 24h.",
                             "en": "No completed trades yet. Data will appear after 24h."},
    "no_logs":              {"fr": "Aucun log disponible.",       "en": "No logs available."},
    "logs_unavailable":     {"fr": "Logs non disponibles (DB non initialisée)", "en": "Logs unavailable (DB not initialized)"},
    "no_open_pos":          {"fr": "Aucune position ouverte.",    "en": "No open positions."},
    # Force run / actions
    "force_run_btn":        {"fr": "Force Run",                  "en": "Force Run"},
    "force_run_ok":         {"fr": "Cycle lancé !",              "en": "Cycle started!"},
    "force_run_running":    {"fr": "Cycle en cours...",          "en": "Running cycle..."},
    "force_run_error":      {"fr": "Erreur Force Run",           "en": "Force Run Error"},
    # Admin
    "logout_btn":           {"fr": "Déconnexion",                "en": "Logout"},
    "tab_dashboard":        {"fr": "Dashboard",                  "en": "Dashboard"},
    "tab_admin":            {"fr": "Administration",             "en": "Administration"},
    "tab_llm":              {"fr": "LLM",                        "en": "LLM"},
    "tab_crawler":          {"fr": "Crawler",                    "en": "Crawler"},
    "tab_news":             {"fr": "News",                       "en": "News"},
    "tab_sources":          {"fr": "Sources",                    "en": "Sources"},
    "tab_mirofish":         {"fr": "MiroFish",                   "en": "MiroFish"},
    "tab_risk":             {"fr": "Risk",                       "en": "Risk"},
    "tab_agents":           {"fr": "Agents",                     "en": "Agents"},
    "tab_logging":          {"fr": "Journalisation",             "en": "Logging"},
    "tab_flux":             {"fr": "Flux Manager",               "en": "Flux Manager"},
    "admin_auth_required":  {"fr": "Cette section nécessite une authentification.",
                             "en": "This section requires authentication."},
    "admin_password":       {"fr": "Mot de passe admin",         "en": "Admin password"},
    "admin_connect":        {"fr": "Se connecter",               "en": "Connect"},
    "wrong_password":       {"fr": "Mot de passe incorrect",     "en": "Wrong password"},
    "admin_error":          {"fr": "Erreur",                     "en": "Error"},
    "save_config_btn":      {"fr": "Sauvegarder la configuration","en": "Save Configuration"},
    "config_saved":         {"fr": "Configuration sauvegardée dans config/settings.yaml",
                             "en": "Configuration saved to config/settings.yaml"},
    "config_error":         {"fr": "Erreur lors de la sauvegarde","en": "Error saving configuration"},
    # BTC live / data
    "btc_price_label":      {"fr": "Prix BTC actuel",            "en": "Current BTC Price"},
    "open_pos_label":       {"fr": "Positions ouvertes",         "en": "Open Positions"},
    "data_load_error":      {"fr": "Impossible de charger les données live",
                             "en": "Cannot load live data"},
    "no_explanation":       {"fr": "Aucune explication disponible.", "en": "No explanation available."},
    "ma50_short":           {"fr": "MA50",                       "en": "MA50"},
}

_current_lang: str = "fr"


def set_lang(lang: str) -> None:
    global _current_lang
    _current_lang = lang if lang in ("fr", "en") else "fr"


def get_lang() -> str:
    return _current_lang


def t(key: str, lang: str | None = None) -> str:
    """Retourne la traduction pour la clé donnée dans la langue courante.
    Fallback : langue demandée → anglais → français → clé brute.
    """
    effective_lang = lang or _current_lang
    entry = _TRANSLATIONS.get(key)
    if entry is None:
        return key
    if effective_lang in entry:
        return entry[effective_lang]
    # Fallback explicite : EN → FR → clé
    return entry.get("en") or entry.get("fr") or key
