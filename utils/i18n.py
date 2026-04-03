"""
utils/i18n.py — Internationalisation (FR / EN / DE / ES / IT / PT / NL / ZH)
Usage :
    from utils.i18n import t
    st.subheader(t("climate_title"))
"""
from __future__ import annotations

_TRANSLATIONS: dict[str, dict[str, str]] = {
    # Dashboard sections
    "climate_title": {
        "fr": "Climat de marché", "en": "Market Climate",
        "de": "Marktklima", "es": "Clima del mercado",
        "it": "Clima di mercato", "pt": "Clima de mercado",
        "nl": "Marktklimaat", "zh": "市场气候",
    },
    "portfolio_title": {
        "fr": "Portefeuille", "en": "Portfolio",
        "de": "Portfolio", "es": "Cartera",
        "it": "Portafoglio", "pt": "Carteira",
        "nl": "Portefeuille", "zh": "投资组合",
    },
    "last_decision_title": {
        "fr": "Dernière décision IA", "en": "Latest AI Decision",
        "de": "Letzte KI-Entscheidung", "es": "Última decisión IA",
        "it": "Ultima decisione IA", "pt": "Última decisão IA",
        "nl": "Laatste AI-beslissing", "zh": "最新AI决策",
    },
    "btc_live_title": {
        "fr": "BTC Live — Positions ouvertes", "en": "BTC Live — Open Positions",
        "de": "BTC Live — Offene Positionen", "es": "BTC en vivo — Posiciones abiertas",
        "it": "BTC Live — Posizioni aperte", "pt": "BTC ao vivo — Posições abertas",
        "nl": "BTC Live — Open posities", "zh": "BTC实时 — 持仓",
    },
    "perf_chart_title": {
        "fr": "Performance cumulée", "en": "Cumulative Performance",
        "de": "Kumulative Performance", "es": "Rendimiento acumulado",
        "it": "Performance cumulata", "pt": "Desempenho acumulado",
        "nl": "Cumulatieve prestatie", "zh": "累计表现",
    },
    "trades_title": {
        "fr": "Historique des trades", "en": "Trade History",
        "de": "Handelshistorie", "es": "Historial de operaciones",
        "it": "Storico operazioni", "pt": "Histórico de operações",
        "nl": "Handelsgeschiedenis", "zh": "交易历史",
    },
    "logs_title": {
        "fr": "Logs temps réel", "en": "Real-time Logs",
        "de": "Echtzeit-Logs", "es": "Logs en tiempo real",
        "it": "Log in tempo reale", "pt": "Logs em tempo real",
        "nl": "Realtime logs", "zh": "实时日志",
    },
    "admin_title": {
        "fr": "Accès Administration", "en": "Admin Access",
        "de": "Admin-Zugang", "es": "Acceso administración",
        "it": "Accesso amministrazione", "pt": "Acesso administrativo",
        "nl": "Admin-toegang", "zh": "管理入口",
    },
    # Metrics
    "score_label": {
        "fr": "Score de conviction", "en": "Conviction Score",
        "de": "Überzeugungswert", "es": "Puntuación de convicción",
        "it": "Punteggio di convinzione", "pt": "Pontuação de convicção",
        "nl": "Overtuigingsscore", "zh": "信念评分",
    },
    "last_decision_label": {
        "fr": "Dernière décision", "en": "Last Decision",
        "de": "Letzte Entscheidung", "es": "Última decisión",
        "it": "Ultima decisione", "pt": "Última decisão",
        "nl": "Laatste beslissing", "zh": "最新决策",
    },
    "last_cycle_label": {
        "fr": "Dernier cycle", "en": "Last Cycle",
        "de": "Letzter Zyklus", "es": "Último ciclo",
        "it": "Ultimo ciclo", "pt": "Último ciclo",
        "nl": "Laatste cyclus", "zh": "上一周期",
    },
    "total_trades_label": {
        "fr": "Total trades", "en": "Total Trades",
        "de": "Trades gesamt", "es": "Total de operaciones",
        "it": "Totale operazioni", "pt": "Total de operações",
        "nl": "Totaal transacties", "zh": "总交易数",
    },
    "ma50_label": {
        "fr": "Tendance MA50", "en": "MA50 Trend",
        "de": "MA50-Trend", "es": "Tendencia MA50",
        "it": "Tendenza MA50", "pt": "Tendência MA50",
        "nl": "MA50-trend", "zh": "MA50趋势",
    },
    "ma50_bull": {
        "fr": "Haussier", "en": "Bullish",
        "de": "Bullisch", "es": "Alcista",
        "it": "Rialzista", "pt": "Altista",
        "nl": "Bullish", "zh": "看涨",
    },
    "ma50_bear": {
        "fr": "Baissier", "en": "Bearish",
        "de": "Bärisch", "es": "Bajista",
        "it": "Ribassista", "pt": "Baixista",
        "nl": "Bearish", "zh": "看跌",
    },
    "buy_blocked": {
        "fr": "BUY bloqué", "en": "BUY blocked",
        "de": "BUY blockiert", "es": "BUY bloqueado",
        "it": "BUY bloccato", "pt": "BUY bloqueado",
        "nl": "BUY geblokkeerd", "zh": "买入已阻止",
    },
    "capital_label": {
        "fr": "Capital initial", "en": "Initial Capital",
        "de": "Anfangskapital", "es": "Capital inicial",
        "it": "Capitale iniziale", "pt": "Capital inicial",
        "nl": "Startkapitaal", "zh": "初始资金",
    },
    "value_label": {
        "fr": "Valeur actuelle", "en": "Current Value",
        "de": "Aktueller Wert", "es": "Valor actual",
        "it": "Valore attuale", "pt": "Valor atual",
        "nl": "Huidige waarde", "zh": "当前价值",
    },
    "pnl_label": {
        "fr": "P&L total", "en": "Total P&L",
        "de": "Gesamt P&L", "es": "P&L total",
        "it": "P&L totale", "pt": "P&L total",
        "nl": "Totaal P&L", "zh": "总盈亏",
    },
    "trades_label": {
        "fr": "Trades exécutés", "en": "Executed Trades",
        "de": "Ausgeführte Trades", "es": "Operaciones ejecutadas",
        "it": "Operazioni eseguite", "pt": "Operações executadas",
        "nl": "Uitgevoerde transacties", "zh": "已执行交易",
    },
    "open_pos_label": {
        "fr": "Positions ouvertes", "en": "Open Positions",
        "de": "Offene Positionen", "es": "Posiciones abiertas",
        "it": "Posizioni aperte", "pt": "Posições abertas",
        "nl": "Open posities", "zh": "持仓",
    },
    "btc_price_label": {
        "fr": "Prix BTC actuel", "en": "Current BTC Price",
        "de": "Aktueller BTC-Preis", "es": "Precio BTC actual",
        "it": "Prezzo BTC attuale", "pt": "Preço BTC atual",
        "nl": "Huidige BTC-prijs", "zh": "当前BTC价格",
    },
    # Table columns
    "col_date": {
        "fr": "Date", "en": "Date",
        "de": "Datum", "es": "Fecha",
        "it": "Data", "pt": "Data",
        "nl": "Datum", "zh": "日期",
    },
    "col_action": {
        "fr": "Action", "en": "Action",
        "de": "Aktion", "es": "Acción",
        "it": "Azione", "pt": "Ação",
        "nl": "Actie", "zh": "操作",
    },
    "col_price": {
        "fr": "Prix entrée", "en": "Entry Price",
        "de": "Einstiegspreis", "es": "Precio de entrada",
        "it": "Prezzo di ingresso", "pt": "Preço de entrada",
        "nl": "Instapprijs", "zh": "入场价",
    },
    "col_entry": {
        "fr": "Prix entrée", "en": "Entry Price",
        "de": "Einstiegspreis", "es": "Precio de entrada",
        "it": "Prezzo di ingresso", "pt": "Preço de entrada",
        "nl": "Instapprijs", "zh": "入场价",
    },
    "col_size": {
        "fr": "Taille ($)", "en": "Size ($)",
        "de": "Größe ($)", "es": "Tamaño ($)",
        "it": "Dimensione ($)", "pt": "Tamanho ($)",
        "nl": "Grootte ($)", "zh": "规模 ($)",
    },
    "col_sl": {
        "fr": "SL", "en": "SL",
        "de": "SL", "es": "SL",
        "it": "SL", "pt": "SL",
        "nl": "SL", "zh": "止损",
    },
    "col_tp": {
        "fr": "TP", "en": "TP",
        "de": "TP", "es": "TP",
        "it": "TP", "pt": "TP",
        "nl": "TP", "zh": "止盈",
    },
    "col_pnl": {
        "fr": "P&L 24h", "en": "P&L 24h",
        "de": "P&L 24h", "es": "P&L 24h",
        "it": "P&L 24h", "pt": "P&L 24h",
        "nl": "P&L 24u", "zh": "24h盈亏",
    },
    "col_score": {
        "fr": "Score", "en": "Score",
        "de": "Score", "es": "Puntuación",
        "it": "Punteggio", "pt": "Pontuação",
        "nl": "Score", "zh": "评分",
    },
    # Status
    "pending": {
        "fr": "⏳ en cours", "en": "⏳ pending",
        "de": "⏳ ausstehend", "es": "⏳ pendiente",
        "it": "⏳ in corso", "pt": "⏳ pendente",
        "nl": "⏳ in behandeling", "zh": "⏳ 进行中",
    },
    "no_trades": {
        "fr": "Aucun trade exécuté pour l'instant.",
        "en": "No trades executed yet.",
        "de": "Noch keine Trades ausgeführt.",
        "es": "Ninguna operación ejecutada aún.",
        "it": "Nessuna operazione eseguita finora.",
        "pt": "Nenhuma operação executada até agora.",
        "nl": "Nog geen transacties uitgevoerd.",
        "zh": "暂无已执行交易。",
    },
    "no_cycle": {
        "fr": "Aucun cycle exécuté. Cliquez sur 'Force Run' pour démarrer.",
        "en": "No cycle run yet. Click 'Force Run' to start.",
        "de": "Noch kein Zyklus ausgeführt. Klicken Sie auf 'Force Run' zum Starten.",
        "es": "Ningún ciclo ejecutado. Haga clic en 'Force Run' para iniciar.",
        "it": "Nessun ciclo eseguito. Clicca su 'Force Run' per avviare.",
        "pt": "Nenhum ciclo executado. Clique em 'Force Run' para iniciar.",
        "nl": "Nog geen cyclus uitgevoerd. Klik op 'Force Run' om te starten.",
        "zh": "尚未运行周期。点击'Force Run'开始。",
    },
    "no_perf_data": {
        "fr": "Pas encore de trades avec résultats. Les données apparaîtront après 24h.",
        "en": "No completed trades yet. Data will appear after 24h.",
        "de": "Noch keine abgeschlossenen Trades. Daten erscheinen nach 24h.",
        "es": "Aún sin operaciones completadas. Los datos aparecerán después de 24h.",
        "it": "Nessuna operazione completata. I dati appariranno dopo 24h.",
        "pt": "Nenhuma operação concluída. Os dados aparecerão após 24h.",
        "nl": "Nog geen afgeronde transacties. Gegevens verschijnen na 24u.",
        "zh": "暂无已完成交易。数据将在24小时后显示。",
    },
    "no_logs": {
        "fr": "Aucun log disponible.", "en": "No logs available.",
        "de": "Keine Logs verfügbar.", "es": "No hay logs disponibles.",
        "it": "Nessun log disponibile.", "pt": "Nenhum log disponível.",
        "nl": "Geen logs beschikbaar.", "zh": "暂无日志。",
    },
    "logs_unavailable": {
        "fr": "Logs non disponibles (DB non initialisée)",
        "en": "Logs unavailable (DB not initialized)",
        "de": "Logs nicht verfügbar (DB nicht initialisiert)",
        "es": "Logs no disponibles (DB no inicializada)",
        "it": "Log non disponibili (DB non inizializzato)",
        "pt": "Logs indisponíveis (DB não inicializado)",
        "nl": "Logs niet beschikbaar (DB niet geïnitialiseerd)",
        "zh": "日志不可用（数据库未初始化）",
    },
    "no_open_pos": {
        "fr": "Aucune position ouverte.", "en": "No open positions.",
        "de": "Keine offenen Positionen.", "es": "Sin posiciones abiertas.",
        "it": "Nessuna posizione aperta.", "pt": "Nenhuma posição aberta.",
        "nl": "Geen open posities.", "zh": "无持仓。",
    },
    # Force run / actions
    "force_run_btn": {
        "fr": "Force Run", "en": "Force Run",
        "de": "Force Run", "es": "Force Run",
        "it": "Force Run", "pt": "Force Run",
        "nl": "Force Run", "zh": "强制运行",
    },
    "force_run_ok": {
        "fr": "Cycle lancé !", "en": "Cycle started!",
        "de": "Zyklus gestartet!", "es": "¡Ciclo iniciado!",
        "it": "Ciclo avviato!", "pt": "Ciclo iniciado!",
        "nl": "Cyclus gestart!", "zh": "周期已启动！",
    },
    "force_run_running": {
        "fr": "Cycle en cours...", "en": "Running cycle...",
        "de": "Zyklus läuft...", "es": "Ciclo en curso...",
        "it": "Ciclo in corso...", "pt": "Ciclo em andamento...",
        "nl": "Cyclus loopt...", "zh": "周期运行中…",
    },
    "force_run_error": {
        "fr": "Erreur Force Run", "en": "Force Run Error",
        "de": "Force-Run-Fehler", "es": "Error de Force Run",
        "it": "Errore Force Run", "pt": "Erro no Force Run",
        "nl": "Force Run-fout", "zh": "强制运行错误",
    },
    # Admin
    "logout_btn": {
        "fr": "Déconnexion", "en": "Logout",
        "de": "Abmelden", "es": "Cerrar sesión",
        "it": "Disconnetti", "pt": "Sair",
        "nl": "Uitloggen", "zh": "退出登录",
    },
    "tab_dashboard": {
        "fr": "Dashboard", "en": "Dashboard",
        "de": "Dashboard", "es": "Panel",
        "it": "Dashboard", "pt": "Painel",
        "nl": "Dashboard", "zh": "仪表盘",
    },
    "tab_admin": {
        "fr": "Administration", "en": "Administration",
        "de": "Verwaltung", "es": "Administración",
        "it": "Amministrazione", "pt": "Administração",
        "nl": "Beheer", "zh": "管理",
    },
    "tab_llm": {
        "fr": "LLM", "en": "LLM",
        "de": "LLM", "es": "LLM",
        "it": "LLM", "pt": "LLM",
        "nl": "LLM", "zh": "LLM",
    },
    "tab_crawler": {
        "fr": "Crawler", "en": "Crawler",
        "de": "Crawler", "es": "Crawler",
        "it": "Crawler", "pt": "Crawler",
        "nl": "Crawler", "zh": "爬虫",
    },
    "tab_news": {
        "fr": "News", "en": "News",
        "de": "Nachrichten", "es": "Noticias",
        "it": "Notizie", "pt": "Notícias",
        "nl": "Nieuws", "zh": "新闻",
    },
    "tab_sources": {
        "fr": "Sources", "en": "Sources",
        "de": "Quellen", "es": "Fuentes",
        "it": "Fonti", "pt": "Fontes",
        "nl": "Bronnen", "zh": "数据源",
    },
    "tab_mirofish": {
        "fr": "MiroFish", "en": "MiroFish",
        "de": "MiroFish", "es": "MiroFish",
        "it": "MiroFish", "pt": "MiroFish",
        "nl": "MiroFish", "zh": "MiroFish",
    },
    "tab_risk": {
        "fr": "Risk", "en": "Risk",
        "de": "Risiko", "es": "Riesgo",
        "it": "Rischio", "pt": "Risco",
        "nl": "Risico", "zh": "风险",
    },
    "tab_agents": {
        "fr": "Agents", "en": "Agents",
        "de": "Agenten", "es": "Agentes",
        "it": "Agenti", "pt": "Agentes",
        "nl": "Agenten", "zh": "代理",
    },
    "tab_logging": {
        "fr": "Journalisation", "en": "Logging",
        "de": "Protokollierung", "es": "Registro",
        "it": "Registrazione", "pt": "Registro",
        "nl": "Logboek", "zh": "日志",
    },
    "tab_flux": {
        "fr": "Flux Manager", "en": "Flux Manager",
        "de": "Flux Manager", "es": "Flux Manager",
        "it": "Flux Manager", "pt": "Flux Manager",
        "nl": "Flux Manager", "zh": "数据流管理",
    },
    "admin_auth_required": {
        "fr": "Cette section nécessite une authentification.",
        "en": "This section requires authentication.",
        "de": "Dieser Bereich erfordert Authentifizierung.",
        "es": "Esta sección requiere autenticación.",
        "it": "Questa sezione richiede l'autenticazione.",
        "pt": "Esta seção requer autenticação.",
        "nl": "Dit gedeelte vereist authenticatie.",
        "zh": "此部分需要身份验证。",
    },
    "admin_password": {
        "fr": "Mot de passe admin", "en": "Admin password",
        "de": "Admin-Passwort", "es": "Contraseña de administrador",
        "it": "Password amministratore", "pt": "Senha de administrador",
        "nl": "Beheerderswachtwoord", "zh": "管理员密码",
    },
    "admin_connect": {
        "fr": "Se connecter", "en": "Connect",
        "de": "Anmelden", "es": "Conectar",
        "it": "Connetti", "pt": "Conectar",
        "nl": "Inloggen", "zh": "登录",
    },
    "wrong_password": {
        "fr": "Mot de passe incorrect", "en": "Wrong password",
        "de": "Falsches Passwort", "es": "Contraseña incorrecta",
        "it": "Password errata", "pt": "Senha incorreta",
        "nl": "Verkeerd wachtwoord", "zh": "密码错误",
    },
    "admin_error": {
        "fr": "Erreur", "en": "Error",
        "de": "Fehler", "es": "Error",
        "it": "Errore", "pt": "Erro",
        "nl": "Fout", "zh": "错误",
    },
    "save_config_btn": {
        "fr": "Sauvegarder la configuration", "en": "Save Configuration",
        "de": "Konfiguration speichern", "es": "Guardar configuración",
        "it": "Salva configurazione", "pt": "Salvar configuração",
        "nl": "Configuratie opslaan", "zh": "保存配置",
    },
    "config_saved": {
        "fr": "Configuration sauvegardée dans config/settings.yaml",
        "en": "Configuration saved to config/settings.yaml",
        "de": "Konfiguration in config/settings.yaml gespeichert",
        "es": "Configuración guardada en config/settings.yaml",
        "it": "Configurazione salvata in config/settings.yaml",
        "pt": "Configuração salva em config/settings.yaml",
        "nl": "Configuratie opgeslagen in config/settings.yaml",
        "zh": "配置已保存至 config/settings.yaml",
    },
    "config_error": {
        "fr": "Erreur lors de la sauvegarde", "en": "Error saving configuration",
        "de": "Fehler beim Speichern", "es": "Error al guardar",
        "it": "Errore durante il salvataggio", "pt": "Erro ao salvar",
        "nl": "Fout bij opslaan", "zh": "保存配置时出错",
    },
    # BTC live / data
    "data_load_error": {
        "fr": "Impossible de charger les données live",
        "en": "Cannot load live data",
        "de": "Live-Daten können nicht geladen werden",
        "es": "No se pueden cargar los datos en vivo",
        "it": "Impossibile caricare i dati in tempo reale",
        "pt": "Não foi possível carregar os dados ao vivo",
        "nl": "Kan live-gegevens niet laden",
        "zh": "无法加载实时数据",
    },
    "no_explanation": {
        "fr": "Aucune explication disponible.", "en": "No explanation available.",
        "de": "Keine Erklärung verfügbar.", "es": "Sin explicación disponible.",
        "it": "Nessuna spiegazione disponibile.", "pt": "Nenhuma explicação disponível.",
        "nl": "Geen uitleg beschikbaar.", "zh": "暂无解释。",
    },
    "ma50_short": {
        "fr": "MA50", "en": "MA50",
        "de": "MA50", "es": "MA50",
        "it": "MA50", "pt": "MA50",
        "nl": "MA50", "zh": "MA50",
    },

    # ── Admin panel – LLM ──
    "cfg_llm_title": {
        "fr": "Configuration LLM", "en": "LLM Configuration",
        "de": "LLM-Konfiguration", "es": "Configuración LLM",
        "it": "Configurazione LLM", "pt": "Configuração LLM",
        "nl": "LLM-configuratie", "zh": "LLM配置",
    },
    "cfg_provider": {
        "fr": "Provider", "en": "Provider",
        "de": "Anbieter", "es": "Proveedor",
        "it": "Provider", "pt": "Provedor",
        "nl": "Provider", "zh": "提供商",
    },
    "cfg_model": {
        "fr": "Modèle", "en": "Model",
        "de": "Modell", "es": "Modelo",
        "it": "Modello", "pt": "Modelo",
        "nl": "Model", "zh": "模型",
    },
    "cfg_temperature": {
        "fr": "Température", "en": "Temperature",
        "de": "Temperatur", "es": "Temperatura",
        "it": "Temperatura", "pt": "Temperatura",
        "nl": "Temperatuur", "zh": "温度",
    },
    "cfg_max_tokens": {
        "fr": "Max tokens", "en": "Max tokens",
        "de": "Max Tokens", "es": "Máx. tokens",
        "it": "Max token", "pt": "Máx. tokens",
        "nl": "Max tokens", "zh": "最大token数",
    },
    "cfg_timeout_llm": {
        "fr": "Timeout LLM (s)", "en": "LLM Timeout (s)",
        "de": "LLM-Timeout (s)", "es": "Timeout LLM (s)",
        "it": "Timeout LLM (s)", "pt": "Timeout LLM (s)",
        "nl": "LLM-timeout (s)", "zh": "LLM超时 (秒)",
    },
    "cfg_timeout_help": {
        "fr": "Délai max avant abandon d'un appel LLM. Si dépassé, le cycle continue avec la synthèse de secours.",
        "en": "Max delay before aborting an LLM call. If exceeded, the cycle continues with the fallback summary.",
        "de": "Maximale Wartezeit vor Abbruch eines LLM-Aufrufs. Bei Überschreitung wird die Fallback-Zusammenfassung verwendet.",
        "es": "Tiempo máximo antes de abortar una llamada LLM. Si se excede, el ciclo continúa con la síntesis de respaldo.",
        "it": "Ritardo massimo prima di interrompere una chiamata LLM. Se superato, il ciclo continua con la sintesi di riserva.",
        "pt": "Tempo máximo antes de abortar uma chamada LLM. Se excedido, o ciclo continua com a síntese de reserva.",
        "nl": "Maximale wachttijd voordat een LLM-aanroep wordt afgebroken. Bij overschrijding wordt de fallback-samenvatting gebruikt.",
        "zh": "中止LLM调用前的最大延迟。超时后将使用备用摘要继续周期。",
    },
    "cfg_cache_responses": {
        "fr": "Cache réponses", "en": "Cache responses",
        "de": "Antworten cachen", "es": "Cachear respuestas",
        "it": "Cache risposte", "pt": "Cache de respostas",
        "nl": "Antwoorden cachen", "zh": "缓存响应",
    },

    # ── Admin panel – Crawler ──
    "cfg_crawler_title": {
        "fr": "Configuration Crawler", "en": "Crawler Configuration",
        "de": "Crawler-Konfiguration", "es": "Configuración del Crawler",
        "it": "Configurazione Crawler", "pt": "Configuração do Crawler",
        "nl": "Crawler-configuratie", "zh": "爬虫配置",
    },
    "cfg_n_themes": {
        "fr": "Nb thèmes", "en": "Themes count",
        "de": "Anzahl Themen", "es": "Nº de temas",
        "it": "N. temi", "pt": "Nº de temas",
        "nl": "Aantal thema's", "zh": "主题数量",
    },
    "cfg_pages_theme": {
        "fr": "Pages/thème", "en": "Pages/theme",
        "de": "Seiten/Thema", "es": "Páginas/tema",
        "it": "Pagine/tema", "pt": "Páginas/tema",
        "nl": "Pagina's/thema", "zh": "页面/主题",
    },
    "cfg_frequency": {
        "fr": "Fréquence", "en": "Frequency",
        "de": "Frequenz", "es": "Frecuencia",
        "it": "Frequenza", "pt": "Frequência",
        "nl": "Frequentie", "zh": "频率",
    },
    "cfg_templates": {
        "fr": "Templates (un par ligne)", "en": "Templates (one per line)",
        "de": "Vorlagen (eine pro Zeile)", "es": "Plantillas (una por línea)",
        "it": "Template (uno per riga)", "pt": "Modelos (um por linha)",
        "nl": "Sjablonen (één per regel)", "zh": "模板（每行一个）",
    },

    # ── Admin panel – News ──
    "cfg_news_title": {
        "fr": "Configuration News", "en": "News Configuration",
        "de": "Nachrichten-Konfiguration", "es": "Configuración de noticias",
        "it": "Configurazione notizie", "pt": "Configuração de notícias",
        "nl": "Nieuwsconfiguratie", "zh": "新闻配置",
    },
    "cfg_polling_interval": {
        "fr": "Intervalle polling (s)", "en": "Polling interval (s)",
        "de": "Abfrageintervall (s)", "es": "Intervalo de sondeo (s)",
        "it": "Intervallo polling (s)", "pt": "Intervalo de polling (s)",
        "nl": "Poll-interval (s)", "zh": "轮询间隔 (秒)",
    },
    "cfg_items_max_cycle": {
        "fr": "Items max/cycle", "en": "Max items/cycle",
        "de": "Max. Einträge/Zyklus", "es": "Máx. ítems/ciclo",
        "it": "Max elementi/ciclo", "pt": "Máx. itens/ciclo",
        "nl": "Max items/cyclus", "zh": "每周期最大项数",
    },
    "cfg_keywords_btc": {
        "fr": "Mots-clés BTC/USDT (séparés par virgules)",
        "en": "BTC/USDT keywords (comma separated)",
        "de": "BTC/USDT Schlüsselwörter (kommagetrennt)",
        "es": "Palabras clave BTC/USDT (separadas por comas)",
        "it": "Parole chiave BTC/USDT (separate da virgole)",
        "pt": "Palavras-chave BTC/USDT (separadas por vírgulas)",
        "nl": "BTC/USDT trefwoorden (kommagescheiden)",
        "zh": "BTC/USDT关键词（逗号分隔）",
    },

    # ── Admin panel – Sources ──
    "cfg_sources_title": {
        "fr": "Sources de collecte d'informations",
        "en": "Data Collection Sources",
        "de": "Datenquellen",
        "es": "Fuentes de recolección de datos",
        "it": "Fonti di raccolta dati",
        "pt": "Fontes de coleta de dados",
        "nl": "Gegevensbronnen",
        "zh": "数据采集源",
    },
    "cfg_rss_title": {
        "fr": "Flux RSS", "en": "RSS Feeds",
        "de": "RSS-Feeds", "es": "Feeds RSS",
        "it": "Feed RSS", "pt": "Feeds RSS",
        "nl": "RSS-feeds", "zh": "RSS订阅",
    },
    "cfg_rss_area": {
        "fr": "Un flux RSS par ligne (URL complète)",
        "en": "One RSS feed per line (full URL)",
        "de": "Ein RSS-Feed pro Zeile (vollständige URL)",
        "es": "Un feed RSS por línea (URL completa)",
        "it": "Un feed RSS per riga (URL completo)",
        "pt": "Um feed RSS por linha (URL completa)",
        "nl": "Eén RSS-feed per regel (volledige URL)",
        "zh": "每行一个RSS订阅（完整URL）",
    },
    "cfg_rss_count": {
        "fr": "{n} flux RSS configurés", "en": "{n} RSS feeds configured",
        "de": "{n} RSS-Feeds konfiguriert", "es": "{n} feeds RSS configurados",
        "it": "{n} feed RSS configurati", "pt": "{n} feeds RSS configurados",
        "nl": "{n} RSS-feeds geconfigureerd", "zh": "已配置 {n} 个RSS订阅",
    },
    "cfg_nitter_title": {
        "fr": "Comptes Twitter/X via Nitter", "en": "Twitter/X accounts via Nitter",
        "de": "Twitter/X-Konten via Nitter", "es": "Cuentas Twitter/X vía Nitter",
        "it": "Account Twitter/X via Nitter", "pt": "Contas Twitter/X via Nitter",
        "nl": "Twitter/X-accounts via Nitter", "zh": "Twitter/X账户（via Nitter）",
    },
    "cfg_nitter_area": {
        "fr": "Un compte par ligne (sans @)", "en": "One account per line (without @)",
        "de": "Ein Konto pro Zeile (ohne @)", "es": "Una cuenta por línea (sin @)",
        "it": "Un account per riga (senza @)", "pt": "Uma conta por linha (sem @)",
        "nl": "Eén account per regel (zonder @)", "zh": "每行一个账户（不含@）",
    },
    "cfg_nitter_count": {
        "fr": "{n} comptes Nitter configurés", "en": "{n} Nitter accounts configured",
        "de": "{n} Nitter-Konten konfiguriert", "es": "{n} cuentas Nitter configuradas",
        "it": "{n} account Nitter configurati", "pt": "{n} contas Nitter configuradas",
        "nl": "{n} Nitter-accounts geconfigureerd", "zh": "已配置 {n} 个Nitter账户",
    },
    "cfg_reddit_title": {
        "fr": "Subreddits Reddit (RSS)", "en": "Reddit Subreddits (RSS)",
        "de": "Reddit Subreddits (RSS)", "es": "Subreddits de Reddit (RSS)",
        "it": "Subreddit Reddit (RSS)", "pt": "Subreddits do Reddit (RSS)",
        "nl": "Reddit Subreddits (RSS)", "zh": "Reddit子版块 (RSS)",
    },
    "cfg_reddit_area": {
        "fr": "Un subreddit par ligne (sans r/)", "en": "One subreddit per line (without r/)",
        "de": "Ein Subreddit pro Zeile (ohne r/)", "es": "Un subreddit por línea (sin r/)",
        "it": "Un subreddit per riga (senza r/)", "pt": "Um subreddit por linha (sem r/)",
        "nl": "Eén subreddit per regel (zonder r/)", "zh": "每行一个子版块（不含r/）",
    },
    "cfg_reddit_count": {
        "fr": "{n} subreddits configurés", "en": "{n} subreddits configured",
        "de": "{n} Subreddits konfiguriert", "es": "{n} subreddits configurados",
        "it": "{n} subreddit configurati", "pt": "{n} subreddits configurados",
        "nl": "{n} subreddits geconfigureerd", "zh": "已配置 {n} 个子版块",
    },
    "cfg_cp_enable": {
        "fr": "Activer CryptoPanic", "en": "Enable CryptoPanic",
        "de": "CryptoPanic aktivieren", "es": "Activar CryptoPanic",
        "it": "Attiva CryptoPanic", "pt": "Ativar CryptoPanic",
        "nl": "CryptoPanic inschakelen", "zh": "启用CryptoPanic",
    },
    "cfg_cp_max": {
        "fr": "Items max", "en": "Max items",
        "de": "Max. Einträge", "es": "Máx. ítems",
        "it": "Max elementi", "pt": "Máx. itens",
        "nl": "Max items", "zh": "最大项数",
    },

    # ── Admin panel – MiroFish ──
    "cfg_mirofish_title": {
        "fr": "Configuration MiroFish", "en": "MiroFish Configuration",
        "de": "MiroFish-Konfiguration", "es": "Configuración MiroFish",
        "it": "Configurazione MiroFish", "pt": "Configuração MiroFish",
        "nl": "MiroFish-configuratie", "zh": "MiroFish配置",
    },
    "cfg_mf_agents": {
        "fr": "Nb agents", "en": "Agent count",
        "de": "Anzahl Agenten", "es": "Nº de agentes",
        "it": "N. agenti", "pt": "Nº de agentes",
        "nl": "Aantal agenten", "zh": "代理数量",
    },
    "cfg_mf_steps": {
        "fr": "Nb steps", "en": "Step count",
        "de": "Anzahl Schritte", "es": "Nº de pasos",
        "it": "N. passi", "pt": "Nº de etapas",
        "nl": "Aantal stappen", "zh": "步数",
    },
    "cfg_mf_news_weight": {
        "fr": "Poids news dans seed", "en": "News weight in seed",
        "de": "Nachrichtengewicht im Seed", "es": "Peso de noticias en seed",
        "it": "Peso notizie nel seed", "pt": "Peso de notícias no seed",
        "nl": "Nieuwsgewicht in seed", "zh": "种子中新闻权重",
    },
    "cfg_mf_adt_weight": {
        "fr": "Poids Air du Temps", "en": "Air du Temps weight",
        "de": "Air du Temps Gewicht", "es": "Peso Air du Temps",
        "it": "Peso Air du Temps", "pt": "Peso Air du Temps",
        "nl": "Air du Temps gewicht", "zh": "Air du Temps权重",
    },

    # ── Admin panel – Risk ──
    "cfg_risk_title": {
        "fr": "Configuration Risk Engine", "en": "Risk Engine Configuration",
        "de": "Risikomanagement-Konfiguration", "es": "Configuración del motor de riesgo",
        "it": "Configurazione motore di rischio", "pt": "Configuração do motor de risco",
        "nl": "Risicomanagementconfiguratie", "zh": "风险引擎配置",
    },
    "cfg_kelly_max": {
        "fr": "Kelly max", "en": "Kelly max",
        "de": "Kelly max", "es": "Kelly máx.",
        "it": "Kelly max", "pt": "Kelly máx.",
        "nl": "Kelly max", "zh": "Kelly最大值",
    },
    "cfg_pos_size": {
        "fr": "Position size (%)", "en": "Position size (%)",
        "de": "Positionsgröße (%)", "es": "Tamaño de posición (%)",
        "it": "Dimensione posizione (%)", "pt": "Tamanho da posição (%)",
        "nl": "Positiegrootte (%)", "zh": "仓位大小 (%)",
    },
    "cfg_max_dd": {
        "fr": "Max drawdown (%)", "en": "Max drawdown (%)",
        "de": "Max. Drawdown (%)", "es": "Drawdown máx. (%)",
        "it": "Max drawdown (%)", "pt": "Drawdown máx. (%)",
        "nl": "Max drawdown (%)", "zh": "最大回撤 (%)",
    },
    "cfg_buy_threshold": {
        "fr": "Seuil BUY", "en": "BUY threshold",
        "de": "BUY-Schwelle", "es": "Umbral de compra",
        "it": "Soglia BUY", "pt": "Limiar de compra",
        "nl": "BUY-drempel", "zh": "买入阈值",
    },
    "cfg_exit_threshold": {
        "fr": "Seuil SELL (sortie)", "en": "SELL threshold (exit)",
        "de": "SELL-Schwelle (Ausstieg)", "es": "Umbral de venta (salida)",
        "it": "Soglia SELL (uscita)", "pt": "Limiar de venda (saída)",
        "nl": "SELL-drempel (uitstap)", "zh": "卖出阈值（退出）",
    },
    "cfg_hitl": {
        "fr": "Human-in-the-loop", "en": "Human-in-the-loop",
        "de": "Human-in-the-Loop", "es": "Humano en el bucle",
        "it": "Umano nel ciclo", "pt": "Humano no loop",
        "nl": "Human-in-the-loop", "zh": "人工确认",
    },
    "cfg_max_open_pos": {
        "fr": "Max positions ouvertes simultanément (0 = illimité)",
        "en": "Max simultaneous open positions (0 = unlimited)",
        "de": "Max. gleichzeitig offene Positionen (0 = unbegrenzt)",
        "es": "Máx. posiciones abiertas simultáneas (0 = ilimitado)",
        "it": "Max posizioni aperte simultanee (0 = illimitato)",
        "pt": "Máx. posições abertas simultâneas (0 = ilimitado)",
        "nl": "Max gelijktijdig open posities (0 = onbeperkt)",
        "zh": "最大同时持仓数（0 = 无限）",
    },
    "cfg_max_open_help": {
        "fr": "Si ce nombre est atteint, les nouveaux BUY sont bloqués jusqu'à clôture d'une position",
        "en": "When this limit is reached, new BUY orders are blocked until a position is closed",
        "de": "Bei Erreichen dieses Limits werden neue BUY-Orders blockiert, bis eine Position geschlossen wird",
        "es": "Al alcanzar este límite, se bloquean nuevas órdenes de compra hasta cerrar una posición",
        "it": "Raggiunto questo limite, i nuovi BUY sono bloccati fino alla chiusura di una posizione",
        "pt": "Ao atingir este limite, novas ordens de compra são bloqueadas até o fechamento de uma posição",
        "nl": "Bij het bereiken van deze limiet worden nieuwe BUY-orders geblokkeerd totdat een positie wordt gesloten",
        "zh": "达到此限制后，新的买入订单将被阻止，直到某个仓位关闭",
    },
    "cfg_ma50_title": {
        "fr": "Filtre tendance MA50 journalière", "en": "Daily MA50 Trend Filter",
        "de": "Täglicher MA50-Trendfilter", "es": "Filtro de tendencia MA50 diario",
        "it": "Filtro tendenza MA50 giornaliero", "pt": "Filtro de tendência MA50 diário",
        "nl": "Dagelijks MA50-trendfilter", "zh": "日线MA50趋势过滤器",
    },
    "cfg_ma50_mode": {
        "fr": "Mode filtre MA50", "en": "MA50 filter mode",
        "de": "MA50-Filtermodus", "es": "Modo filtro MA50",
        "it": "Modalità filtro MA50", "pt": "Modo filtro MA50",
        "nl": "MA50-filtermodus", "zh": "MA50过滤模式",
    },
    "cfg_ma50_score_min": {
        "fr": "Score min BUY sous MA50", "en": "Min BUY score below MA50",
        "de": "Min. BUY-Score unter MA50", "es": "Puntuación mín. BUY bajo MA50",
        "it": "Punteggio min BUY sotto MA50", "pt": "Pontuação mín. BUY abaixo MA50",
        "nl": "Min BUY-score onder MA50", "zh": "MA50下方最低买入评分",
    },
    "cfg_ma50_score_help": {
        "fr": "Score minimum requis pour BUY quand prix < MA50 (mode gradual)",
        "en": "Minimum score required for BUY when price < MA50 (gradual mode)",
        "de": "Mindest-Score für BUY bei Preis < MA50 (gradueller Modus)",
        "es": "Puntuación mínima para BUY cuando precio < MA50 (modo gradual)",
        "it": "Punteggio minimo per BUY quando prezzo < MA50 (modalità graduale)",
        "pt": "Pontuação mínima para BUY quando preço < MA50 (modo gradual)",
        "nl": "Minimumscore voor BUY wanneer prijs < MA50 (geleidelijke modus)",
        "zh": "价格低于MA50时买入所需的最低评分（渐进模式）",
    },
    "cfg_ma50_size_factor": {
        "fr": "Facteur taille sous MA50", "en": "Size factor below MA50",
        "de": "Größenfaktor unter MA50", "es": "Factor de tamaño bajo MA50",
        "it": "Fattore dimensione sotto MA50", "pt": "Fator de tamanho abaixo MA50",
        "nl": "Grootte-factor onder MA50", "zh": "MA50下方仓位因子",
    },
    "cfg_ma50_size_help": {
        "fr": "Multiplicateur appliqué à la taille de position quand prix < MA50",
        "en": "Multiplier applied to position size when price < MA50",
        "de": "Multiplikator für die Positionsgröße bei Preis < MA50",
        "es": "Multiplicador aplicado al tamaño de posición cuando precio < MA50",
        "it": "Moltiplicatore applicato alla dimensione della posizione quando prezzo < MA50",
        "pt": "Multiplicador aplicado ao tamanho da posição quando preço < MA50",
        "nl": "Vermenigvuldiger toegepast op positiegrootte wanneer prijs < MA50",
        "zh": "价格低于MA50时应用于仓位大小的乘数",
    },

    # ── Admin panel – Agents ──
    "cfg_agents_title": {
        "fr": "Activation des agents", "en": "Agent Activation",
        "de": "Agenten-Aktivierung", "es": "Activación de agentes",
        "it": "Attivazione agenti", "pt": "Ativação de agentes",
        "nl": "Agenten activeren", "zh": "代理激活",
    },
    "cfg_agent_toggle": {
        "fr": "Agent {name}", "en": "Agent {name}",
        "de": "Agent {name}", "es": "Agente {name}",
        "it": "Agente {name}", "pt": "Agente {name}",
        "nl": "Agent {name}", "zh": "代理 {name}",
    },
    "cfg_agent_weight": {
        "fr": "Poids {name}", "en": "Weight {name}",
        "de": "Gewicht {name}", "es": "Peso {name}",
        "it": "Peso {name}", "pt": "Peso {name}",
        "nl": "Gewicht {name}", "zh": "权重 {name}",
    },

    # ── Admin panel – TimesFM ──
    "cfg_timesfm_title": {
        "fr": "Configuration TimesFM", "en": "TimesFM Configuration",
        "de": "TimesFM-Konfiguration", "es": "Configuración TimesFM",
        "it": "Configurazione TimesFM", "pt": "Configuração TimesFM",
        "nl": "TimesFM-configuratie", "zh": "TimesFM配置",
    },
    "cfg_tfm_horizon": {
        "fr": "Horizon forecast (candles)", "en": "Forecast horizon (candles)",
        "de": "Prognosehorizont (Kerzen)", "es": "Horizonte de pronóstico (velas)",
        "it": "Orizzonte previsione (candele)", "pt": "Horizonte de previsão (candles)",
        "nl": "Prognose-horizon (kaarsen)", "zh": "预测周期（蜡烛数）",
    },
    "cfg_tfm_horizon_help": {
        "fr": "Nombre de candles à prédire (ex : 24 × 15min = 6h)",
        "en": "Number of candles to forecast (e.g. 24 × 15min = 6h)",
        "de": "Anzahl vorherzusagender Kerzen (z.B. 24 × 15min = 6h)",
        "es": "Número de velas a predecir (ej: 24 × 15min = 6h)",
        "it": "Numero di candele da prevedere (es: 24 × 15min = 6h)",
        "pt": "Número de candles a prever (ex: 24 × 15min = 6h)",
        "nl": "Aantal te voorspellen kaarsen (bijv. 24 × 15min = 6u)",
        "zh": "预测蜡烛数量（例：24 × 15分钟 = 6小时）",
    },
    "tab_timesfm": {
        "fr": "TimesFM", "en": "TimesFM",
        "de": "TimesFM", "es": "TimesFM",
        "it": "TimesFM", "pt": "TimesFM",
        "nl": "TimesFM", "zh": "TimesFM",
    },

    # ── Admin panel – TimesFM Performance ──
    "cfg_tfm_perf_title": {
        "fr": "Performance des prédictions", "en": "Forecast Performance",
        "de": "Prognose-Performance", "es": "Rendimiento de pronósticos",
        "it": "Performance delle previsioni", "pt": "Desempenho das previsões",
        "nl": "Prestatie van voorspellingen", "zh": "预测表现",
    },
    "cfg_tfm_no_data": {
        "fr": "Aucune prédiction TimesFM enregistrée. Les données apparaîtront après le premier cycle avec TimesFM activé.",
        "en": "No TimesFM forecasts recorded yet. Data will appear after the first cycle with TimesFM enabled.",
        "de": "Noch keine TimesFM-Prognosen aufgezeichnet. Daten erscheinen nach dem ersten Zyklus mit aktiviertem TimesFM.",
        "es": "Sin pronósticos TimesFM registrados. Los datos aparecerán después del primer ciclo con TimesFM activado.",
        "it": "Nessuna previsione TimesFM registrata. I dati appariranno dopo il primo ciclo con TimesFM attivato.",
        "pt": "Nenhuma previsão TimesFM registrada. Os dados aparecerão após o primeiro ciclo com TimesFM ativado.",
        "nl": "Nog geen TimesFM-voorspellingen geregistreerd. Gegevens verschijnen na de eerste cyclus met TimesFM ingeschakeld.",
        "zh": "暂无TimesFM预测记录。数据将在启用TimesFM的首次周期后显示。",
    },
    "cfg_tfm_total": {
        "fr": "Prédictions", "en": "Forecasts",
        "de": "Prognosen", "es": "Pronósticos",
        "it": "Previsioni", "pt": "Previsões",
        "nl": "Voorspellingen", "zh": "预测数",
    },
    "cfg_tfm_evaluated": {
        "fr": "Évaluées", "en": "Evaluated",
        "de": "Ausgewertet", "es": "Evaluadas",
        "it": "Valutate", "pt": "Avaliadas",
        "nl": "Geëvalueerd", "zh": "已评估",
    },
    "cfg_tfm_dir_acc": {
        "fr": "Direction correcte", "en": "Direction Accuracy",
        "de": "Richtungsgenauigkeit", "es": "Precisión de dirección",
        "it": "Accuratezza direzione", "pt": "Precisão de direção",
        "nl": "Richtingsnauwkeurigheid", "zh": "方向准确率",
    },
    "cfg_tfm_mae": {
        "fr": "MAE (%)", "en": "MAE (%)",
        "de": "MAE (%)", "es": "MAE (%)",
        "it": "MAE (%)", "pt": "MAE (%)",
        "nl": "MAE (%)", "zh": "MAE (%)",
    },
    "cfg_tfm_confidence": {
        "fr": "Confiance moy.", "en": "Avg Confidence",
        "de": "Durchschn. Konfidenz", "es": "Confianza prom.",
        "it": "Confidenza media", "pt": "Confiança média",
        "nl": "Gem. vertrouwen", "zh": "平均置信度",
    },
    "cfg_tfm_latency": {
        "fr": "Latence moy.", "en": "Avg Latency",
        "de": "Durchschn. Latenz", "es": "Latencia prom.",
        "it": "Latenza media", "pt": "Latência média",
        "nl": "Gem. latentie", "zh": "平均延迟",
    },
    "cfg_tfm_recent": {
        "fr": "Dernières prédictions évaluées", "en": "Recent Evaluated Forecasts",
        "de": "Letzte ausgewertete Prognosen", "es": "Últimos pronósticos evaluados",
        "it": "Ultime previsioni valutate", "pt": "Últimas previsões avaliadas",
        "nl": "Recent geëvalueerde voorspellingen", "zh": "最近已评估预测",
    },
    "cfg_tfm_pending": {
        "fr": "Prédictions en attente", "en": "Pending Forecasts",
        "de": "Ausstehende Prognosen", "es": "Pronósticos pendientes",
        "it": "Previsioni in attesa", "pt": "Previsões pendentes",
        "nl": "Openstaande voorspellingen", "zh": "待评估预测",
    },

    # ── Admin panel – Logging ──
    "cfg_logging_title": {
        "fr": "Configuration Logging", "en": "Logging Configuration",
        "de": "Logging-Konfiguration", "es": "Configuración de registro",
        "it": "Configurazione registrazione", "pt": "Configuração de registro",
        "nl": "Logconfiguratie", "zh": "日志配置",
    },
    "cfg_log_level": {
        "fr": "Niveau log", "en": "Log level",
        "de": "Log-Level", "es": "Nivel de log",
        "it": "Livello log", "pt": "Nível de log",
        "nl": "Logniveau", "zh": "日志级别",
    },
    "cfg_alert_threshold": {
        "fr": "Seuil alerte Telegram/Discord", "en": "Telegram/Discord alert threshold",
        "de": "Telegram/Discord Alarmschwelle", "es": "Umbral de alerta Telegram/Discord",
        "it": "Soglia avviso Telegram/Discord", "pt": "Limiar de alerta Telegram/Discord",
        "nl": "Telegram/Discord-drempel", "zh": "Telegram/Discord警报阈值",
    },

    # ── Admin panel – Users ──
    "tab_users": {
        "fr": "Utilisateurs", "en": "Users",
        "de": "Benutzer", "es": "Usuarios",
        "it": "Utenti", "pt": "Usuários",
        "nl": "Gebruikers", "zh": "用户",
    },

    # ── Misc admin ──
    "cfg_load_error": {
        "fr": "Impossible de charger settings.yaml",
        "en": "Unable to load settings.yaml",
        "de": "settings.yaml kann nicht geladen werden",
        "es": "No se puede cargar settings.yaml",
        "it": "Impossibile caricare settings.yaml",
        "pt": "Não foi possível carregar settings.yaml",
        "nl": "Kan settings.yaml niet laden",
        "zh": "无法加载 settings.yaml",
    },

    # ── Force Run — step labels ──
    "run_cycle_running": {
        "fr": "Cycle en cours…", "en": "Running cycle…",
        "de": "Zyklus läuft…", "es": "Ciclo en curso…",
        "it": "Ciclo in corso…", "pt": "Ciclo em andamento…",
        "nl": "Cyclus loopt…", "zh": "周期运行中…",
    },
    "run_step_news": {
        "fr": "News rapides (RSS / NewsAPI)", "en": "Fast news (RSS / NewsAPI)",
        "de": "Schnelle Nachrichten (RSS / NewsAPI)", "es": "Noticias rápidas (RSS / NewsAPI)",
        "it": "Notizie rapide (RSS / NewsAPI)", "pt": "Notícias rápidas (RSS / NewsAPI)",
        "nl": "Snel nieuws (RSS / NewsAPI)", "zh": "快讯（RSS / NewsAPI）",
    },
    "run_step_crawl": {
        "fr": "Crawl web thématique", "en": "Thematic web crawl",
        "de": "Thematischer Web-Crawl", "es": "Rastreo web temático",
        "it": "Crawl web tematico", "pt": "Crawl web temático",
        "nl": "Thematische webcrawl", "zh": "主题网页爬取",
    },
    "run_step_mirofish": {
        "fr": "Simulation MiroFish (swarm)", "en": "MiroFish simulation (swarm)",
        "de": "MiroFish-Simulation (Schwarm)", "es": "Simulación MiroFish (swarm)",
        "it": "Simulazione MiroFish (swarm)", "pt": "Simulação MiroFish (swarm)",
        "nl": "MiroFish-simulatie (zwerm)", "zh": "MiroFish仿真（群体）",
    },
    "run_step_market": {
        "fr": "Données marché (OHLCV / orderbook)", "en": "Market data (OHLCV / orderbook)",
        "de": "Marktdaten (OHLCV / Orderbuch)", "es": "Datos de mercado (OHLCV / orderbook)",
        "it": "Dati di mercato (OHLCV / orderbook)", "pt": "Dados de mercado (OHLCV / orderbook)",
        "nl": "Marktgegevens (OHLCV / orderboek)", "zh": "市场数据（OHLCV / 订单簿）",
    },
    "run_step_agents": {
        "fr": "Analyse agents (fundamental, X…)", "en": "Agent analysis (fundamental, X…)",
        "de": "Agentenanalyse (Fundamental, X…)", "es": "Análisis de agentes (fundamental, X…)",
        "it": "Analisi agenti (fondamentale, X…)", "pt": "Análise de agentes (fundamental, X…)",
        "nl": "Agentanalyse (fundamenteel, X…)", "zh": "代理分析（基本面、X…）",
    },
    "run_step_synth": {
        "fr": "Synthèse LLM finale", "en": "Final LLM synthesis",
        "de": "Finale LLM-Synthese", "es": "Síntesis LLM final",
        "it": "Sintesi LLM finale", "pt": "Síntese LLM final",
        "nl": "Finale LLM-synthese", "zh": "LLM最终综合",
    },
    "run_step_score": {
        "fr": "Calcul du score global", "en": "Global score calculation",
        "de": "Gesamtscore-Berechnung", "es": "Cálculo de puntuación global",
        "it": "Calcolo del punteggio globale", "pt": "Cálculo da pontuação global",
        "nl": "Globale scoreberekening", "zh": "全局评分计算",
    },
    "run_step_decide": {
        "fr": "Décision (BUY / SELL / HOLD)", "en": "Decision (BUY / SELL / HOLD)",
        "de": "Entscheidung (BUY / SELL / HOLD)", "es": "Decisión (BUY / SELL / HOLD)",
        "it": "Decisione (BUY / SELL / HOLD)", "pt": "Decisão (BUY / SELL / HOLD)",
        "nl": "Beslissing (BUY / SELL / HOLD)", "zh": "决策（BUY / SELL / HOLD）",
    },
    "run_no_news_abort": {
        "fr": "Aucune news — cycle interrompu", "en": "No news — cycle aborted",
        "de": "Keine Nachrichten — Zyklus abgebrochen", "es": "Sin noticias — ciclo interrumpido",
        "it": "Nessuna notizia — ciclo interrotto", "pt": "Sem notícias — ciclo interrompido",
        "nl": "Geen nieuws — cyclus afgebroken", "zh": "无新闻——周期已中止",
    },
    "run_news_count": {
        "fr": "{n} news", "en": "{n} news",
        "de": "{n} Nachrichten", "es": "{n} noticias",
        "it": "{n} notizie", "pt": "{n} notícias",
        "nl": "{n} nieuws", "zh": "{n} 条新闻",
    },
    "run_status": {
        "fr": "statut", "en": "status",
        "de": "Status", "es": "estado",
        "it": "stato", "pt": "estado",
        "nl": "status", "zh": "状态",
    },
    "run_signal": {
        "fr": "signal", "en": "signal",
        "de": "Signal", "es": "señal",
        "it": "segnale", "pt": "sinal",
        "nl": "signaal", "zh": "信号",
    },
    "run_conf": {
        "fr": "conf", "en": "conf",
        "de": "Konf", "es": "conf",
        "it": "conf", "pt": "conf",
        "nl": "conf", "zh": "置信度",
    },
    "run_agents_count": {
        "fr": "{n} agents, {e} erreurs", "en": "{n} agents, {e} errors",
        "de": "{n} Agenten, {e} Fehler", "es": "{n} agentes, {e} errores",
        "it": "{n} agenti, {e} errori", "pt": "{n} agentes, {e} erros",
        "nl": "{n} agenten, {e} fouten", "zh": "{n} 个代理，{e} 个错误",
    },
    "run_trade_exec": {
        "fr": "Exécution du trade", "en": "Trade execution",
        "de": "Trade-Ausführung", "es": "Ejecución de la operación",
        "it": "Esecuzione dell'operazione", "pt": "Execução da operação",
        "nl": "Handelsuitvoering", "zh": "执行交易",
    },
    "run_trade_done": {
        "fr": "Trade exécuté", "en": "Trade executed",
        "de": "Trade ausgeführt", "es": "Operación ejecutada",
        "it": "Operazione eseguita", "pt": "Operação executada",
        "nl": "Handel uitgevoerd", "zh": "交易已执行",
    },
    "run_trade_failed": {
        "fr": "Exécution échouée", "en": "Execution failed",
        "de": "Ausführung fehlgeschlagen", "es": "Ejecución fallida",
        "it": "Esecuzione fallita", "pt": "Execução falhou",
        "nl": "Uitvoering mislukt", "zh": "执行失败",
    },
    "run_done": {
        "fr": "Cycle terminé", "en": "Cycle completed",
        "de": "Zyklus abgeschlossen", "es": "Ciclo completado",
        "it": "Ciclo completato", "pt": "Ciclo concluído",
        "nl": "Cyclus voltooid", "zh": "周期完成",
    },
    "run_done_errors": {
        "fr": "Cycle terminé avec {n} erreur(s)", "en": "Cycle completed with {n} error(s)",
        "de": "Zyklus abgeschlossen mit {n} Fehler(n)", "es": "Ciclo completado con {n} error(es)",
        "it": "Ciclo completato con {n} errore/i", "pt": "Ciclo concluído com {n} erro(s)",
        "nl": "Cyclus voltooid met {n} fout(en)", "zh": "周期完成，{n} 个错误",
    },
    "run_already_running": {
        "fr": "Une analyse est déjà en cours…", "en": "An analysis is already running…",
        "de": "Eine Analyse läuft bereits…", "es": "Un análisis ya está en curso…",
        "it": "Un'analisi è già in corso…", "pt": "Uma análise já está em andamento…",
        "nl": "Er loopt al een analyse…", "zh": "分析已在进行中…",
    },
    "run_agents_parallel": {
        "fr": "Lancement de {n} agents en parallèle…", "en": "Launching {n} agents in parallel…",
        "de": "{n} Agenten werden parallel gestartet…", "es": "Lanzando {n} agentes en paralelo…",
        "it": "Avvio di {n} agenti in parallelo…", "pt": "Lançando {n} agentes em paralelo…",
        "nl": "{n} agenten parallel gestart…", "zh": "并行启动 {n} 个代理…",
    },
    "run_agent_done": {
        "fr": "{name} — {signal} (score {score:.0f}, {ms}ms)",
        "en": "{name} — {signal} (score {score:.0f}, {ms}ms)",
        "de": "{name} — {signal} (Score {score:.0f}, {ms}ms)",
        "es": "{name} — {signal} (puntuación {score:.0f}, {ms}ms)",
        "it": "{name} — {signal} (punteggio {score:.0f}, {ms}ms)",
        "pt": "{name} — {signal} (pontuação {score:.0f}, {ms}ms)",
        "nl": "{name} — {signal} (score {score:.0f}, {ms}ms)",
        "zh": "{name} — {signal}（评分 {score:.0f}，{ms}ms）",
    },
    "run_agent_error": {
        "fr": "{name} — erreur : {err}", "en": "{name} — error: {err}",
        "de": "{name} — Fehler: {err}", "es": "{name} — error: {err}",
        "it": "{name} — errore: {err}", "pt": "{name} — erro: {err}",
        "nl": "{name} — fout: {err}", "zh": "{name} — 错误：{err}",
    },

    # ── Decision Engine — explanation narrative ──
    "dec_decision": {
        "fr": "Décision", "en": "Decision",
        "de": "Entscheidung", "es": "Decisión",
        "it": "Decisione", "pt": "Decisão",
        "nl": "Beslissing", "zh": "决策",
    },
    "dec_conviction": {
        "fr": "score de conviction", "en": "conviction score",
        "de": "Überzeugungswert", "es": "puntuación de convicción",
        "it": "punteggio di convinzione", "pt": "pontuação de convicção",
        "nl": "overtuigingsscore", "zh": "信念评分",
    },
    "dec_mirofish": {
        "fr": "Analyse MiroFish", "en": "MiroFish Analysis",
        "de": "MiroFish-Analyse", "es": "Análisis MiroFish",
        "it": "Analisi MiroFish", "pt": "Análise MiroFish",
        "nl": "MiroFish-analyse", "zh": "MiroFish分析",
    },
    "dec_agents": {
        "fr": "Agents", "en": "Agents",
        "de": "Agenten", "es": "Agentes",
        "it": "Agenti", "pt": "Agentes",
        "nl": "Agenten", "zh": "代理",
    },
    "dec_market": {
        "fr": "Marché", "en": "Market",
        "de": "Markt", "es": "Mercado",
        "it": "Mercato", "pt": "Mercado",
        "nl": "Markt", "zh": "市场",
    },
    "dec_ai_summary": {
        "fr": "Synthèse IA", "en": "AI Summary",
        "de": "KI-Zusammenfassung", "es": "Resumen IA",
        "it": "Sintesi IA", "pt": "Resumo IA",
        "nl": "AI-samenvatting", "zh": "AI摘要",
    },
    "dec_rsi_oversold": {
        "fr": "survendu", "en": "oversold",
        "de": "überverkauft", "es": "sobrevendido",
        "it": "ipervenduto", "pt": "sobrevendido",
        "nl": "oververkocht", "zh": "超卖",
    },
    "dec_rsi_overbought": {
        "fr": "suracheté", "en": "overbought",
        "de": "überkauft", "es": "sobrecomprado",
        "it": "ipercomprato", "pt": "sobrecomprado",
        "nl": "overbought", "zh": "超买",
    },
    "dec_rsi_neutral": {
        "fr": "neutre", "en": "neutral",
        "de": "neutral", "es": "neutral",
        "it": "neutrale", "pt": "neutro",
        "nl": "neutraal", "zh": "中性",
    },
    "dec_neutral_zone": {
        "fr": "Le score {score} est dans la zone neutre [{lo}–{hi}]. Surveillance maintenue.",
        "en": "Score {score} is within the neutral zone [{lo}–{hi}]. Monitoring maintained.",
        "de": "Score {score} liegt in der neutralen Zone [{lo}–{hi}]. Überwachung fortgesetzt.",
        "es": "La puntuación {score} está en la zona neutral [{lo}–{hi}]. Monitoreo mantenido.",
        "it": "Il punteggio {score} è nella zona neutra [{lo}–{hi}]. Monitoraggio mantenuto.",
        "pt": "A pontuação {score} está na zona neutra [{lo}–{hi}]. Monitoramento mantido.",
        "nl": "Score {score} bevindt zich in de neutrale zone [{lo}–{hi}]. Monitoring voortgezet.",
        "zh": "评分 {score} 在中性区间 [{lo}–{hi}]。持续监控中。",
    },
    "dec_ma50_blocked": {
        "fr": "⚠️ **Filtre MA50 actif** : score={score} haussier mais le prix ({price}) est sous la MA50 journalière ({ma50}). BUY bloqué — tendance macro baissière.",
        "en": "⚠️ **MA50 Filter active**: score={score} bullish but price ({price}) is below daily MA50 ({ma50}). BUY blocked — bearish macro trend.",
        "de": "⚠️ **MA50-Filter aktiv**: Score={score} bullisch, aber Preis ({price}) unter dem täglichen MA50 ({ma50}). BUY blockiert — bärischer Makrotrend.",
        "es": "⚠️ **Filtro MA50 activo**: score={score} alcista pero el precio ({price}) está por debajo de la MA50 diaria ({ma50}). BUY bloqueado — tendencia macro bajista.",
        "it": "⚠️ **Filtro MA50 attivo**: score={score} rialzista ma il prezzo ({price}) è sotto la MA50 giornaliera ({ma50}). BUY bloccato — trend macro ribassista.",
        "pt": "⚠️ **Filtro MA50 ativo**: score={score} altista mas o preço ({price}) está abaixo da MA50 diária ({ma50}). BUY bloqueado — tendência macro baixista.",
        "nl": "⚠️ **MA50-filter actief**: score={score} bullish maar prijs ({price}) onder dagelijkse MA50 ({ma50}). BUY geblokkeerd — bearish macrotrend.",
        "zh": "⚠️ **MA50过滤器激活**：评分={score} 看涨，但价格 ({price}) 低于日线MA50 ({ma50})。买入已阻止——宏观下行趋势。",
    },
    "dec_ma50_strong": {
        "fr": "⚠️ **Signal fort sous MA50** : score={score} ≥ seuil fort. BUY autorisé mais taille réduite ×{factor} (prix {price} sous MA50 {ma50}).",
        "en": "⚠️ **Strong signal below MA50**: score={score} ≥ strong threshold. BUY allowed but size reduced ×{factor} (price {price} below MA50 {ma50}).",
        "de": "⚠️ **Starkes Signal unter MA50**: Score={score} ≥ starke Schwelle. BUY erlaubt, aber Größe reduziert ×{factor} (Preis {price} unter MA50 {ma50}).",
        "es": "⚠️ **Señal fuerte bajo MA50**: score={score} ≥ umbral fuerte. BUY permitido pero tamaño reducido ×{factor} (precio {price} bajo MA50 {ma50}).",
        "it": "⚠️ **Segnale forte sotto MA50**: score={score} ≥ soglia forte. BUY consentito ma dimensione ridotta ×{factor} (prezzo {price} sotto MA50 {ma50}).",
        "pt": "⚠️ **Sinal forte abaixo da MA50**: score={score} ≥ limiar forte. BUY permitido mas tamanho reduzido ×{factor} (preço {price} abaixo da MA50 {ma50}).",
        "nl": "⚠️ **Sterk signaal onder MA50**: score={score} ≥ sterke drempel. BUY toegestaan maar grootte verminderd ×{factor} (prijs {price} onder MA50 {ma50}).",
        "zh": "⚠️ **MA50下方强信号**：评分={score} ≥ 强信号阈值。允许买入但仓位缩小 ×{factor}（价格 {price} 低于MA50 {ma50}）。",
    },
    "dec_buy_signal": {
        "fr": "Les signaux convergent vers un sentiment haussier. Score de conviction élevé ({score}/100) au-dessus du seuil d'achat ({threshold}).",
        "en": "Signals converge toward bullish sentiment. High conviction score ({score}/100) above buy threshold ({threshold}).",
        "de": "Signale konvergieren zu bullischer Stimmung. Hoher Überzeugungswert ({score}/100) über Kaufschwelle ({threshold}).",
        "es": "Las señales convergen hacia un sentimiento alcista. Alta puntuación de convicción ({score}/100) por encima del umbral de compra ({threshold}).",
        "it": "I segnali convergono verso un sentimento rialzista. Alto punteggio di convinzione ({score}/100) sopra la soglia di acquisto ({threshold}).",
        "pt": "Os sinais convergem para um sentimento altista. Alta pontuação de convicção ({score}/100) acima do limiar de compra ({threshold}).",
        "nl": "Signalen convergeren naar bullish sentiment. Hoge overtuigingsscore ({score}/100) boven koopdrempel ({threshold}).",
        "zh": "信号趋向看涨。高信念评分 ({score}/100) 高于买入阈值 ({threshold})。",
    },
    "dec_sell_signal": {
        "fr": "Les signaux indiquent une pression baissière. Score de conviction ({score}/100) sous le seuil de sortie ({threshold}) — position longue clôturée.",
        "en": "Signals indicate bearish pressure. Conviction score ({score}/100) below exit threshold ({threshold}) — long position closed.",
        "de": "Signale deuten auf bärischen Druck. Überzeugungswert ({score}/100) unter Ausstiegsschwelle ({threshold}) — Long-Position geschlossen.",
        "es": "Las señales indican presión bajista. Puntuación de convicción ({score}/100) por debajo del umbral de salida ({threshold}) — posición larga cerrada.",
        "it": "I segnali indicano pressione ribassista. Punteggio di convinzione ({score}/100) sotto la soglia di uscita ({threshold}) — posizione lunga chiusa.",
        "pt": "Os sinais indicam pressão baixista. Pontuação de convicção ({score}/100) abaixo do limiar de saída ({threshold}) — posição longa encerrada.",
        "nl": "Signalen duiden op bearish druk. Overtuigingsscore ({score}/100) onder uitstapdrempel ({threshold}) — longpositie gesloten.",
        "zh": "信号显示看跌压力。信念评分 ({score}/100) 低于退出阈值 ({threshold})——多头仓位已平仓。",
    },

    # Shadow Profiles / Comparison
    "profiles_title": {
        "fr": "Comparaison des profils", "en": "Profile Comparison",
        "de": "Profilvergleich", "es": "Comparación de perfiles",
        "it": "Confronto dei profili", "pt": "Comparação de perfis",
        "nl": "Profielvergelijking", "zh": "配置对比",
    },
    "profiles_no_data": {
        "fr": "Pas encore de données de comparaison. Les profils shadow seront évalués au prochain cycle.",
        "en": "No comparison data yet. Shadow profiles will be evaluated next cycle.",
        "de": "Noch keine Vergleichsdaten. Shadow-Profile werden im nächsten Zyklus ausgewertet.",
        "es": "Aún no hay datos de comparación. Los perfiles shadow se evaluarán en el próximo ciclo.",
        "it": "Nessun dato di confronto. I profili shadow verranno valutati al prossimo ciclo.",
        "pt": "Ainda sem dados de comparação. Os perfis shadow serão avaliados no próximo ciclo.",
        "nl": "Nog geen vergelijkingsdata. Shadow-profielen worden volgend cyclus geëvalueerd.",
        "zh": "暂无对比数据。影子配置将在下一个周期中评估。",
    },
    "profiles_trades": {
        "fr": "Trades", "en": "Trades",
        "de": "Trades", "es": "Operaciones",
        "it": "Operazioni", "pt": "Operações",
        "nl": "Transacties", "zh": "交易",
    },
    "profiles_winrate": {
        "fr": "Win Rate", "en": "Win Rate",
        "de": "Gewinnrate", "es": "Tasa de acierto",
        "it": "Win Rate", "pt": "Taxa de acerto",
        "nl": "Winstpercentage", "zh": "胜率",
    },
    "profiles_total_pnl": {
        "fr": "P&L Total", "en": "Total P&L",
        "de": "Gesamt-P&L", "es": "P&L Total",
        "it": "P&L Totale", "pt": "P&L Total",
        "nl": "Totale P&L", "zh": "总盈亏",
    },
    "profiles_avg_pnl": {
        "fr": "P&L Moyen", "en": "Avg P&L",
        "de": "Ø P&L", "es": "P&L Promedio",
        "it": "P&L Medio", "pt": "P&L Médio",
        "nl": "Gem. P&L", "zh": "平均盈亏",
    },
    "profiles_cumulative": {
        "fr": "P&L cumulé par profil", "en": "Cumulative P&L by Profile",
        "de": "Kumuliertes P&L pro Profil", "es": "P&L acumulado por perfil",
        "it": "P&L cumulato per profilo", "pt": "P&L acumulado por perfil",
        "nl": "Cumulatief P&L per profiel", "zh": "各配置累计盈亏",
    },
}

_current_lang: str = "en"

SUPPORTED_LANGS = {
    "fr": "Français",
    "en": "English",
    "de": "Deutsch",
    "es": "Español",
    "it": "Italiano",
    "pt": "Português",
    "nl": "Nederlands",
    "zh": "中文",
}


def set_lang(lang: str) -> None:
    global _current_lang
    _current_lang = lang if lang in SUPPORTED_LANGS else "en"


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
