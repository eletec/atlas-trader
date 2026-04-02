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

    # ── Admin panel – LLM ──
    "cfg_llm_title":        {"fr": "Configuration LLM",          "en": "LLM Configuration"},
    "cfg_provider":         {"fr": "Provider",                   "en": "Provider"},
    "cfg_model":            {"fr": "Modèle",                     "en": "Model"},
    "cfg_temperature":      {"fr": "Température",                "en": "Temperature"},
    "cfg_max_tokens":       {"fr": "Max tokens",                 "en": "Max tokens"},
    "cfg_timeout_llm":      {"fr": "Timeout LLM (s)",            "en": "LLM Timeout (s)"},
    "cfg_timeout_help":     {"fr": "Délai max avant abandon d'un appel LLM. Si dépassé, le cycle continue avec la synthèse de secours.",
                             "en": "Max delay before aborting an LLM call. If exceeded, the cycle continues with the fallback summary."},
    "cfg_cache_responses":  {"fr": "Cache réponses",             "en": "Cache responses"},

    # ── Admin panel – Crawler ──
    "cfg_crawler_title":    {"fr": "Configuration Crawler",      "en": "Crawler Configuration"},
    "cfg_n_themes":         {"fr": "Nb thèmes",                  "en": "Themes count"},
    "cfg_pages_theme":      {"fr": "Pages/thème",                "en": "Pages/theme"},
    "cfg_frequency":        {"fr": "Fréquence",                  "en": "Frequency"},
    "cfg_templates":        {"fr": "Templates (un par ligne)",   "en": "Templates (one per line)"},

    # ── Admin panel – News ──
    "cfg_news_title":       {"fr": "Configuration News",         "en": "News Configuration"},
    "cfg_polling_interval": {"fr": "Intervalle polling (s)",     "en": "Polling interval (s)"},
    "cfg_items_max_cycle":  {"fr": "Items max/cycle",            "en": "Max items/cycle"},
    "cfg_keywords_btc":     {"fr": "Mots-clés BTC/USDT (séparés par virgules)",
                             "en": "BTC/USDT keywords (comma separated)"},

    # ── Admin panel – Sources ──
    "cfg_sources_title":    {"fr": "Sources de collecte d'informations",
                             "en": "Data Collection Sources"},
    "cfg_rss_title":        {"fr": "Flux RSS",                   "en": "RSS Feeds"},
    "cfg_rss_area":         {"fr": "Un flux RSS par ligne (URL complète)",
                             "en": "One RSS feed per line (full URL)"},
    "cfg_rss_count":        {"fr": "{n} flux RSS configurés",    "en": "{n} RSS feeds configured"},
    "cfg_nitter_title":     {"fr": "Comptes Twitter/X via Nitter","en": "Twitter/X accounts via Nitter"},
    "cfg_nitter_area":      {"fr": "Un compte par ligne (sans @)","en": "One account per line (without @)"},
    "cfg_nitter_count":     {"fr": "{n} comptes Nitter configurés","en": "{n} Nitter accounts configured"},
    "cfg_reddit_title":     {"fr": "Subreddits Reddit (RSS)",    "en": "Reddit Subreddits (RSS)"},
    "cfg_reddit_area":      {"fr": "Un subreddit par ligne (sans r/)","en": "One subreddit per line (without r/)"},
    "cfg_reddit_count":     {"fr": "{n} subreddits configurés",  "en": "{n} subreddits configured"},
    "cfg_cp_enable":        {"fr": "Activer CryptoPanic",        "en": "Enable CryptoPanic"},
    "cfg_cp_max":           {"fr": "Items max",                  "en": "Max items"},

    # ── Admin panel – MiroFish ──
    "cfg_mirofish_title":   {"fr": "Configuration MiroFish",     "en": "MiroFish Configuration"},
    "cfg_mf_agents":        {"fr": "Nb agents",                  "en": "Agent count"},
    "cfg_mf_steps":         {"fr": "Nb steps",                   "en": "Step count"},
    "cfg_mf_news_weight":   {"fr": "Poids news dans seed",       "en": "News weight in seed"},
    "cfg_mf_adt_weight":    {"fr": "Poids Air du Temps",         "en": "Air du Temps weight"},

    # ── Admin panel – Risk ──
    "cfg_risk_title":       {"fr": "Configuration Risk Engine",  "en": "Risk Engine Configuration"},
    "cfg_kelly_max":        {"fr": "Kelly max",                  "en": "Kelly max"},
    "cfg_pos_size":         {"fr": "Position size (%)",          "en": "Position size (%)"},
    "cfg_max_dd":           {"fr": "Max drawdown (%)",           "en": "Max drawdown (%)"},
    "cfg_buy_threshold":    {"fr": "Seuil BUY",                  "en": "BUY threshold"},
    "cfg_exit_threshold":   {"fr": "Seuil SELL (sortie)",        "en": "SELL threshold (exit)"},
    "cfg_hitl":             {"fr": "Human-in-the-loop",          "en": "Human-in-the-loop"},
    "cfg_max_open_pos":     {"fr": "Max positions ouvertes simultanément (0 = illimité)",
                             "en": "Max simultaneous open positions (0 = unlimited)"},
    "cfg_max_open_help":    {"fr": "Si ce nombre est atteint, les nouveaux BUY sont bloqués jusqu'à clôture d'une position",
                             "en": "When this limit is reached, new BUY orders are blocked until a position is closed"},
    "cfg_ma50_title":       {"fr": "Filtre tendance MA50 journalière",
                             "en": "Daily MA50 Trend Filter"},
    "cfg_ma50_mode":        {"fr": "Mode filtre MA50",           "en": "MA50 filter mode"},
    "cfg_ma50_score_min":   {"fr": "Score min BUY sous MA50",    "en": "Min BUY score below MA50"},
    "cfg_ma50_score_help":  {"fr": "Score minimum requis pour BUY quand prix < MA50 (mode gradual)",
                             "en": "Minimum score required for BUY when price < MA50 (gradual mode)"},
    "cfg_ma50_size_factor": {"fr": "Facteur taille sous MA50",   "en": "Size factor below MA50"},
    "cfg_ma50_size_help":   {"fr": "Multiplicateur appliqué à la taille de position quand prix < MA50",
                             "en": "Multiplier applied to position size when price < MA50"},

    # ── Admin panel – Agents ──
    "cfg_agents_title":     {"fr": "Activation des agents",      "en": "Agent Activation"},
    "cfg_agent_toggle":     {"fr": "Agent {name}",               "en": "Agent {name}"},
    "cfg_agent_weight":     {"fr": "Poids {name}",               "en": "Weight {name}"},

    # ── Admin panel – Logging ──
    "cfg_logging_title":    {"fr": "Configuration Logging",      "en": "Logging Configuration"},
    "cfg_log_level":        {"fr": "Niveau log",                 "en": "Log level"},
    "cfg_alert_threshold":  {"fr": "Seuil alerte Telegram/Discord","en": "Telegram/Discord alert threshold"},

    # ── Admin panel – Users ──
    "tab_users":            {"fr": "Utilisateurs",               "en": "Users"},

    # ── Misc admin ──
    "cfg_load_error":       {"fr": "Impossible de charger settings.yaml",
                             "en": "Unable to load settings.yaml"},
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
