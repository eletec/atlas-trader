"""
utils/i18n.py — Internationalisation (FR / EN / DE / ES / IT / PT / NL / ZH)
Usage :
    from utils.i18n import t
    st.subheader(t("portfolio_title"))
"""
from __future__ import annotations

_TRANSLATIONS: dict[str, dict[str, str]] = {
    # Dashboard sections
    "portfolio_title": {
        "fr": "Portefeuille", "en": "Portfolio",
        "de": "Portfolio", "es": "Cartera",
        "it": "Portafoglio", "pt": "Carteira",
        "nl": "Portefeuille", "zh": "投资组合",
    },
    "perf_chart_title": {
        "fr": "Performance cumulée", "en": "Cumulative Performance",
        "de": "Kumulative Performance", "es": "Rendimiento acumulado",
        "it": "Performance cumulata", "pt": "Desempenho acumulado",
        "nl": "Cumulatieve prestatie", "zh": "累计表现",
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
    "col_entry": {
        "fr": "Prix entrée", "en": "Entry Price",
        "de": "Einstiegspreis", "es": "Precio de entrada",
        "it": "Prezzo di ingresso", "pt": "Preço de entrada",
        "nl": "Instapprijs", "zh": "入场价",
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
    # Force run / actions
    # Admin
    "logout_btn": {
        "fr": "Déconnexion", "en": "Logout",
        "de": "Abmelden", "es": "Cerrar sesión",
        "it": "Disconnetti", "pt": "Sair",
        "nl": "Uitloggen", "zh": "退出登录",
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
    # BTC live / data

    # ── Admin panel – LLM ──

    # ── Admin panel – Crawler ──

    # ── Admin panel – News ──

    # ── Admin panel – Sources ──

    # ── Admin panel – MiroFish ──

    # ── Admin panel – Risk ──

    # ── Admin panel – Exchange / Simulation ──

    # ── Admin panel – Agents ──

    # ── Admin panel – TimesFM ──

    # ── Admin panel – Market Regime ──

    # ── Admin panel – TimesFM Performance ──

    # ── Admin panel – Kronos ──

    # ── Admin panel – Logging ──

    # ── Admin panel – Tab info texts ──
    "cfg_users_info": {
        "fr": "Gérez les comptes utilisateur du dashboard et leurs niveaux d'accès. L'authentification à deux facteurs (2FA) est gérée ici. Les administrateurs ont accès à tous les paramètres. Les utilisateurs en lecture seule peuvent voir le dashboard mais ne peuvent pas modifier la configuration.",
        "en": "Manage dashboard user accounts and their access levels. Two-factor authentication (2FA) is managed here. Administrators have access to all settings. Read-only users can view the dashboard but cannot modify configuration.",
        "de": "Verwalten Sie Dashboard-Benutzerkonten und ihre Zugriffsebenen. Zwei-Faktor-Authentifizierung (2FA) wird hier verwaltet. Administratoren haben Zugriff auf alle Einstellungen. Nur-Lese-Benutzer können das Dashboard sehen, aber nicht konfigurieren.",
        "es": "Gestione las cuentas de usuario del dashboard y sus niveles de acceso. La autenticación de dos factores (2FA) se gestiona aquí. Los administradores tienen acceso a todos los ajustes. Los usuarios de solo lectura pueden ver el dashboard pero no modificar la configuración.",
        "it": "Gestisci gli account utente del dashboard e i loro livelli di accesso. L'autenticazione a due fattori (2FA) è gestita qui. Gli amministratori hanno accesso a tutte le impostazioni. Gli utenti in sola lettura possono visualizzare il dashboard ma non modificare la configurazione.",
        "pt": "Gerencie contas de usuário do dashboard e seus níveis de acesso. A autenticação de dois fatores (2FA) é gerenciada aqui. Administradores têm acesso a todas as configurações. Usuários somente leitura podem ver o dashboard mas não modificar a configuração.",
        "nl": "Beheer gebruikersaccounts van het dashboard en hun toegangsniveaus. Tweefactorauthenticatie (2FA) wordt hier beheerd. Beheerders hebben toegang tot alle instellingen. Alleen-lezen gebruikers kunnen het dashboard bekijken maar de configuratie niet wijzigen.",
        "zh": "管理仪表板用户账户及其访问级别。双因素认证（2FA）在此管理。管理员可以访问所有设置。只读用户可以查看仪表板但不能修改配置。",
    },

    # ── Admin panel – Control tooltips ──

    # ── Admin panel – Users ──

    # ── Misc admin ──

    # ── Force Run — step labels ──
    "run_already_running": {
        "fr": "Une analyse est déjà en cours…", "en": "An analysis is already running…",
        "de": "Eine Analyse läuft bereits…", "es": "Un análisis ya está en curso…",
        "it": "Un'analisi è già in corso…", "pt": "Uma análise já está em andamento…",
        "nl": "Er loopt al een analyse…", "zh": "分析已在进行中…",
    },

    # ── Decision Engine — explanation narrative ──

    # Shadow Profiles / Comparison

    # ── Hamburger menu ──
    "hbg_admin": {
        "fr": "Administration", "en": "Administration",
        "de": "Verwaltung", "es": "Administración",
        "it": "Amministrazione", "pt": "Administração",
        "nl": "Beheer", "zh": "管理",
    },
    "hbg_theme": {
        "fr": "Thème", "en": "Theme",
        "de": "Thema", "es": "Tema",
        "it": "Tema", "pt": "Tema",
        "nl": "Thema", "zh": "主题",
    },
    "theme_light": {
        "fr": "Clair", "en": "Light",
        "de": "Hell", "es": "Claro",
        "it": "Chiaro", "pt": "Claro",
        "nl": "Licht", "zh": "浅色",
    },
    "theme_dark": {
        "fr": "Sombre", "en": "Dark",
        "de": "Dunkel", "es": "Oscuro",
        "it": "Scuro", "pt": "Escuro",
        "nl": "Donker", "zh": "深色",
    },
    "theme_system": {
        "fr": "Système", "en": "System",
        "de": "System", "es": "Sistema",
        "it": "Sistema", "pt": "Sistema",
        "nl": "Systeem", "zh": "系统",
    },
    "hbg_lang": {
        "fr": "Langue", "en": "Language",
        "de": "Sprache", "es": "Idioma",
        "it": "Lingua", "pt": "Idioma",
        "nl": "Taal", "zh": "语言",
    },
    "hbg_refresh": {
        "fr": "Rafraîchir", "en": "Refresh",
        "de": "Aktualisieren", "es": "Actualizar",
        "it": "Aggiorna", "pt": "Atualizar",
        "nl": "Vernieuwen", "zh": "刷新",
    },

    # ── LLM admin tab ──

    # ── Users admin (auth.py) ──
    "usr_title": {
        "fr": "Gestion des utilisateurs", "en": "User Management",
        "de": "Benutzerverwaltung", "es": "Gestión de usuarios",
        "it": "Gestione utenti", "pt": "Gestão de utilizadores",
        "nl": "Gebruikersbeheer", "zh": "用户管理",
    },
    "usr_session_settings": {
        "fr": "Paramètres de session", "en": "Session Settings",
        "de": "Sitzungseinstellungen", "es": "Configuración de sesión",
        "it": "Impostazioni di sessione", "pt": "Configurações de sessão",
        "nl": "Sessie-instellingen", "zh": "会话设置",
    },
    "usr_guest_mode": {
        "fr": "Mode invité (front visible sans connexion)",
        "en": "Guest mode (front accessible without login)",
        "de": "Gastmodus (Front ohne Anmeldung zugänglich)",
        "es": "Modo invitado (front accesible sin inicio de sesión)",
        "it": "Modalità ospite (front accessibile senza login)",
        "pt": "Modo convidado (front acessível sem login)",
        "nl": "Gastmodus (front toegankelijk zonder inloggen)",
        "zh": "访客模式（无需登录即可访问前端）",
    },
    "usr_guest_help": {
        "fr": "Si activé, le front est accessible sans login. Le back-office nécessite toujours une authentification.",
        "en": "If enabled, the front is accessible without login. The back-office always requires authentication.",
        "de": "Wenn aktiviert, ist das Front ohne Anmeldung zugänglich. Das Back-Office erfordert immer eine Authentifizierung.",
        "es": "Si está activado, el front es accesible sin login. El back-office siempre requiere autenticación.",
        "it": "Se abilitato, il front è accessibile senza login. Il back-office richiede sempre l'autenticazione.",
        "pt": "Se ativado, o front está acessível sem login. O back-office sempre requer autenticação.",
        "nl": "Indien ingeschakeld, is het front toegankelijk zonder inloggen. Het back-office vereist altijd authenticatie.",
        "zh": "启用后，前端无需登录即可访问。后台始终需要身份验证。",
    },
    "usr_session_days": {
        "fr": "Durée de session (jours)", "en": "Session duration (days)",
        "de": "Sitzungsdauer (Tage)", "es": "Duración de sesión (días)",
        "it": "Durata sessione (giorni)", "pt": "Duração da sessão (dias)",
        "nl": "Sessieduur (dagen)", "zh": "会话时长（天）",
    },
    "usr_session_days_help": {
        "fr": "Durée de vie du cookie de session.",
        "en": "Session cookie lifetime.",
        "de": "Lebensdauer des Sitzungs-Cookies.",
        "es": "Vida útil de la cookie de sesión.",
        "it": "Durata del cookie di sessione.",
        "pt": "Tempo de vida do cookie de sessão.",
        "nl": "Levensduur van het sessiecookie.",
        "zh": "会话 Cookie 的有效期。",
    },
    "usr_users_configured": {
        "fr": "Utilisateurs configurés", "en": "Configured users",
        "de": "Konfigurierte Benutzer", "es": "Usuarios configurados",
        "it": "Utenti configurati", "pt": "Utilizadores configurados",
        "nl": "Geconfigureerde gebruikers", "zh": "已配置的用户",
    },
    "usr_no_users": {
        "fr": "Aucun utilisateur. L'assistant de création s'affiche à la prochaine connexion.",
        "en": "No users. The creation wizard will appear at the next login.",
        "de": "Keine Benutzer. Der Einrichtungsassistent erscheint beim nächsten Login.",
        "es": "Sin usuarios. El asistente de creación aparecerá en el próximo inicio de sesión.",
        "it": "Nessun utente. La procedura guidata di creazione apparirà al prossimo accesso.",
        "pt": "Sem utilizadores. O assistente de criação aparecerá no próximo login.",
        "nl": "Geen gebruikers. De aanmaakvizard verschijnt bij de volgende aanmelding.",
        "zh": "没有用户。创建向导将在下次登录时显示。",
    },
    "usr_access_front": {
        "fr": "Accès Front", "en": "Front Access",
        "de": "Front-Zugang", "es": "Acceso Front",
        "it": "Accesso Front", "pt": "Acesso Front",
        "nl": "Front-toegang", "zh": "前端访问",
    },
    "usr_access_back": {
        "fr": "Accès Back-office (+ 2FA obligatoire)",
        "en": "Back-office Access (+ mandatory 2FA)",
        "de": "Back-Office-Zugang (+ 2FA obligatorisch)",
        "es": "Acceso Back-office (+ 2FA obligatorio)",
        "it": "Accesso Back-office (+ 2FA obbligatorio)",
        "pt": "Acesso Back-office (+ 2FA obrigatório)",
        "nl": "Back-office toegang (+ verplichte 2FA)",
        "zh": "后台访问（+ 强制 2FA）",
    },
    "usr_change_pwd": {
        "fr": "Changer le mot de passe", "en": "Change password",
        "de": "Passwort ändern", "es": "Cambiar contraseña",
        "it": "Cambia password", "pt": "Mudar senha",
        "nl": "Wachtwoord wijzigen", "zh": "修改密码",
    },
    "usr_new_pwd": {
        "fr": "Nouveau mot de passe", "en": "New password",
        "de": "Neues Passwort", "es": "Nueva contraseña",
        "it": "Nuova password", "pt": "Nova senha",
        "nl": "Nieuw wachtwoord", "zh": "新密码",
    },
    "usr_update_pwd": {
        "fr": "Mettre à jour", "en": "Update",
        "de": "Aktualisieren", "es": "Actualizar",
        "it": "Aggiorna", "pt": "Atualizar",
        "nl": "Bijwerken", "zh": "更新",
    },
    "usr_pwd_updated": {
        "fr": "Mot de passe mis à jour.", "en": "Password updated.",
        "de": "Passwort aktualisiert.", "es": "Contraseña actualizada.",
        "it": "Password aggiornata.", "pt": "Senha atualizada.",
        "nl": "Wachtwoord bijgewerkt.", "zh": "密码已更新。",
    },
    "usr_min_8": {
        "fr": "Minimum 8 caractères.", "en": "Minimum 8 characters.",
        "de": "Mindestens 8 Zeichen.", "es": "Mínimo 8 caracteres.",
        "it": "Minimo 8 caratteri.", "pt": "Mínimo 8 caracteres.",
        "nl": "Minimaal 8 tekens.", "zh": "最少 8 个字符。",
    },
    "usr_reset_2fa": {
        "fr": "🔄 Réinitialiser le 2FA (nouveau QR code à la prochaine connexion)",
        "en": "🔄 Reset 2FA (new QR code at next login)",
        "de": "🔄 2FA zurücksetzen (neuer QR-Code beim nächsten Login)",
        "es": "🔄 Restablecer 2FA (nuevo código QR en el próximo inicio de sesión)",
        "it": "🔄 Reimposta 2FA (nuovo QR code al prossimo accesso)",
        "pt": "🔄 Redefinir 2FA (novo QR code no próximo login)",
        "nl": "🔄 2FA resetten (nieuwe QR-code bij volgende aanmelding)",
        "zh": "🔄 重置 2FA（下次登录时扫新二维码）",
    },
    "usr_reset_2fa_ok": {
        "fr": "2FA réinitialisé — l'utilisateur devra re-scanner le QR code.",
        "en": "2FA reset — the user will need to re-scan the QR code.",
        "de": "2FA zurückgesetzt — der Benutzer muss den QR-Code erneut scannen.",
        "es": "2FA restablecido — el usuario deberá volver a escanear el código QR.",
        "it": "2FA reimpostato — l'utente dovrà eseguire di nuovo la scansione del QR code.",
        "pt": "2FA redefinido — o utilizador terá de digitalizar novamente o código QR.",
        "nl": "2FA gereset — de gebruiker moet de QR-code opnieuw scannen.",
        "zh": "2FA 已重置——用户需要重新扫描二维码。",
    },
    "usr_delete_btn": {
        "fr": "🗑 Supprimer {uname}", "en": "🗑 Delete {uname}",
        "de": "🗑 Löschen {uname}", "es": "🗑 Eliminar {uname}",
        "it": "🗑 Elimina {uname}", "pt": "🗑 Excluir {uname}",
        "nl": "🗑 Verwijder {uname}", "zh": "🗑 删除 {uname}",
    },
    "usr_deleted_ok": {
        "fr": "Utilisateur '{uname}' supprimé.", "en": "User '{uname}' deleted.",
        "de": "Benutzer '{uname}' gelöscht.", "es": "Usuario '{uname}' eliminado.",
        "it": "Utente '{uname}' eliminato.", "pt": "Utilizador '{uname}' eliminado.",
        "nl": "Gebruiker '{uname}' verwijderd.", "zh": "用户 '{uname}' 已删除。",
    },
    "usr_add_title": {
        "fr": "Ajouter un utilisateur", "en": "Add a user",
        "de": "Benutzer hinzufügen", "es": "Añadir un usuario",
        "it": "Aggiungi un utente", "pt": "Adicionar um utilizador",
        "nl": "Gebruiker toevoegen", "zh": "添加用户",
    },
    "usr_new_username": {
        "fr": "Identifiant", "en": "Username",
        "de": "Benutzername", "es": "Nombre de usuario",
        "it": "Nome utente", "pt": "Nome de utilizador",
        "nl": "Gebruikersnaam", "zh": "用户名",
    },
    "usr_new_password": {
        "fr": "Mot de passe", "en": "Password",
        "de": "Passwort", "es": "Contraseña",
        "it": "Password", "pt": "Senha",
        "nl": "Wachtwoord", "zh": "密码",
    },
    "usr_confirm_pwd": {
        "fr": "Confirmer", "en": "Confirm",
        "de": "Bestätigen", "es": "Confirmar",
        "it": "Conferma", "pt": "Confirmar",
        "nl": "Bevestigen", "zh": "确认",
    },
    "usr_access_back_2fa": {
        "fr": "Accès Back-office (+ 2FA)", "en": "Back-office Access (+ 2FA)",
        "de": "Back-Office-Zugang (+ 2FA)", "es": "Acceso Back-office (+ 2FA)",
        "it": "Accesso Back-office (+ 2FA)", "pt": "Acesso Back-office (+ 2FA)",
        "nl": "Back-office toegang (+ 2FA)", "zh": "后台访问（+ 2FA）",
    },
    "usr_add_btn": {
        "fr": "Ajouter", "en": "Add",
        "de": "Hinzufügen", "es": "Añadir",
        "it": "Aggiungi", "pt": "Adicionar",
        "nl": "Toevoegen", "zh": "添加",
    },
    "usr_id_required": {
        "fr": "L'identifiant est obligatoire.", "en": "Username is required.",
        "de": "Benutzername ist erforderlich.", "es": "El nombre de usuario es obligatorio.",
        "it": "Il nome utente è obbligatorio.", "pt": "O nome de utilizador é obrigatório.",
        "nl": "Gebruikersnaam is verplicht.", "zh": "用户名不能为空。",
    },
    "usr_already_exists": {
        "fr": "L'utilisateur '{uname}' existe déjà.", "en": "User '{uname}' already exists.",
        "de": "Benutzer '{uname}' existiert bereits.", "es": "El usuario '{uname}' ya existe.",
        "it": "L'utente '{uname}' esiste già.", "pt": "O utilizador '{uname}' já existe.",
        "nl": "Gebruiker '{uname}' bestaat al.", "zh": "用户 '{uname}' 已存在。",
    },
    "usr_pwd_mismatch": {
        "fr": "Les mots de passe ne correspondent pas.",
        "en": "Passwords do not match.",
        "de": "Passwörter stimmen nicht überein.",
        "es": "Las contraseñas no coinciden.",
        "it": "Le password non corrispondono.",
        "pt": "As senhas não coincidem.",
        "nl": "Wachtwoorden komen niet overeen.",
        "zh": "两次输入的密码不一致。",
    },
    "usr_created_ok": {
        "fr": "✅ Utilisateur '{uname}' créé.",
        "en": "✅ User '{uname}' created.",
        "de": "✅ Benutzer '{uname}' erstellt.",
        "es": "✅ Usuario '{uname}' creado.",
        "it": "✅ Utente '{uname}' creato.",
        "pt": "✅ Utilizador '{uname}' criado.",
        "nl": "✅ Gebruiker '{uname}' aangemaakt.",
        "zh": "✅ 用户 '{uname}' 已创建。",
    },

    # ── Login form ──
    "login_username": {
        "fr": "Identifiant", "en": "Username",
        "de": "Benutzername", "es": "Usuario",
        "it": "Nome utente", "pt": "Utilizador",
        "nl": "Gebruikersnaam", "zh": "用户名",
    },
    "login_password": {
        "fr": "Mot de passe", "en": "Password",
        "de": "Passwort", "es": "Contraseña",
        "it": "Password", "pt": "Senha",
        "nl": "Wachtwoord", "zh": "密码",
    },
    "login_btn": {
        "fr": "Connexion", "en": "Login",
        "de": "Anmelden", "es": "Iniciar sesión",
        "it": "Accedi", "pt": "Entrar",
        "nl": "Inloggen", "zh": "登录",
    },
    "login_wrong": {
        "fr": "Identifiant ou mot de passe incorrect.",
        "en": "Incorrect username or password.",
        "de": "Benutzername oder Passwort falsch.",
        "es": "Usuario o contraseña incorrectos.",
        "it": "Nome utente o password errati.",
        "pt": "Utilizador ou senha incorretos.",
        "nl": "Onjuiste gebruikersnaam of wachtwoord.",
        "zh": "用户名或密码错误。",
    },
    "login_locked": {
        "fr": "Trop de tentatives échouées. Réessayez dans {s}s.",
        "en": "Too many failed attempts. Try again in {s}s.",
        "de": "Zu viele fehlgeschlagene Versuche. Versuchen Sie es in {s}s erneut.",
        "es": "Demasiados intentos fallidos. Inténtelo de nuevo en {s}s.",
        "it": "Troppi tentativi falliti. Riprova tra {s}s.",
        "pt": "Demasiadas tentativas falhadas. Tente novamente em {s}s.",
        "nl": "Te veel mislukte pogingen. Probeer het over {s}s opnieuw.",
        "zh": "失败次数过多。请 {s} 秒后重试。",
    },

    # ── First setup ──
    "setup_info": {
        "fr": "Aucun utilisateur configuré. Créez votre compte **administrateur** ci-dessous.",
        "en": "No users configured. Create your **administrator** account below.",
        "de": "Keine Benutzer konfiguriert. Erstellen Sie unten Ihr **Administrator**-Konto.",
        "es": "Sin usuarios configurados. Cree su cuenta de **administrador** a continuación.",
        "it": "Nessun utente configurato. Crea il tuo account **amministratore** qui sotto.",
        "pt": "Nenhum utilizador configurado. Crie a sua conta de **administrador** abaixo.",
        "nl": "Geen gebruikers geconfigureerd. Maak hieronder uw **beheerder**-account aan.",
        "zh": "未配置任何用户。请在下方创建您的**管理员**账户。",
    },
    "setup_username": {
        "fr": "Identifiant admin", "en": "Admin username",
        "de": "Admin-Benutzername", "es": "Usuario administrador",
        "it": "Nome utente admin", "pt": "Utilizador admin",
        "nl": "Beheerdernaam", "zh": "管理员用户名",
    },
    "setup_pwd_hint": {
        "fr": "Mot de passe (min. 8 caractères)", "en": "Password (min. 8 characters)",
        "de": "Passwort (mind. 8 Zeichen)", "es": "Contraseña (mín. 8 caracteres)",
        "it": "Password (min. 8 caratteri)", "pt": "Senha (mín. 8 caracteres)",
        "nl": "Wachtwoord (min. 8 tekens)", "zh": "密码（最少 8 位）",
    },
    "setup_confirm_pwd": {
        "fr": "Confirmer le mot de passe", "en": "Confirm password",
        "de": "Passwort bestätigen", "es": "Confirmar contraseña",
        "it": "Conferma password", "pt": "Confirmar senha",
        "nl": "Wachtwoord bevestigen", "zh": "确认密码",
    },
    "setup_create_btn": {
        "fr": "Créer le compte", "en": "Create account",
        "de": "Konto erstellen", "es": "Crear cuenta",
        "it": "Crea account", "pt": "Criar conta",
        "nl": "Account aanmaken", "zh": "创建账户",
    },
    "setup_pwd_min_err": {
        "fr": "Le mot de passe doit contenir au moins 8 caractères.",
        "en": "Password must be at least 8 characters.",
        "de": "Das Passwort muss mindestens 8 Zeichen enthalten.",
        "es": "La contraseña debe tener al menos 8 caracteres.",
        "it": "La password deve contenere almeno 8 caratteri.",
        "pt": "A senha deve ter pelo menos 8 caracteres.",
        "nl": "Wachtwoord moet minimaal 8 tekens bevatten.",
        "zh": "密码至少需要 8 个字符。",
    },
    "setup_success": {
        "fr": "✅ Compte '{uname}' créé. La prochaine connexion configurera le 2FA.",
        "en": "✅ Account '{uname}' created. The next login will set up 2FA.",
        "de": "✅ Konto '{uname}' erstellt. Beim nächsten Login wird 2FA eingerichtet.",
        "es": "✅ Cuenta '{uname}' creada. El próximo inicio de sesión configurará el 2FA.",
        "it": "✅ Account '{uname}' creato. Il prossimo accesso configurerà il 2FA.",
        "pt": "✅ Conta '{uname}' criada. O próximo login configurará o 2FA.",
        "nl": "✅ Account '{uname}' aangemaakt. De volgende login configureert 2FA.",
        "zh": "✅ 账户 '{uname}' 已创建。下次登录将配置双因素认证。",
    },

    # ── TOTP setup ──
    "totp_setup_info": {
        "fr": "**Première connexion admin.** Scannez ce QR code avec votre application d'authentification, puis entrez le code à 6 chiffres pour confirmer.",
        "en": "**First admin login.** Scan this QR code with your authenticator app, then enter the 6-digit code to confirm.",
        "de": "**Erster Admin-Login.** Scannen Sie diesen QR-Code mit Ihrer Authenticator-App und geben Sie dann den 6-stelligen Code zur Bestätigung ein.",
        "es": "**Primer inicio de sesión admin.** Escanee este código QR con su aplicación de autenticación y luego ingrese el código de 6 dígitos para confirmar.",
        "it": "**Primo accesso admin.** Scansiona questo QR code con la tua app di autenticazione, poi inserisci il codice a 6 cifre per confermare.",
        "pt": "**Primeiro login admin.** Digitalize este código QR com a sua app de autenticação e introduza o código de 6 dígitos para confirmar.",
        "nl": "**Eerste admin-login.** Scan deze QR-code met uw authenticator-app en voer vervolgens de 6-cijferige code in ter bevestiging.",
        "zh": "**首次管理员登录。** 用您的认证应用扫描此二维码，然后输入 6 位验证码以确认。",
    },
    "totp_manual_key": {
        "fr": "**Clé à saisir manuellement :**", "en": "**Manual entry key:**",
        "de": "**Manuell einzugebender Schlüssel:**", "es": "**Clave para introducir manualmente:**",
        "it": "**Chiave da inserire manualmente:**", "pt": "**Chave para inserção manual:**",
        "nl": "**Handmatig in te voeren sleutel:**", "zh": "**手动输入密钥：**",
    },
    "totp_compat": {
        "fr": "Compatible : Google Authenticator · Authy · Bitwarden · 1Password",
        "en": "Compatible: Google Authenticator · Authy · Bitwarden · 1Password",
        "de": "Kompatibel: Google Authenticator · Authy · Bitwarden · 1Password",
        "es": "Compatible: Google Authenticator · Authy · Bitwarden · 1Password",
        "it": "Compatibile: Google Authenticator · Authy · Bitwarden · 1Password",
        "pt": "Compatível: Google Authenticator · Authy · Bitwarden · 1Password",
        "nl": "Compatibel: Google Authenticator · Authy · Bitwarden · 1Password",
        "zh": "兼容：Google Authenticator · Authy · Bitwarden · 1Password",
    },
    "totp_code_input": {
        "fr": "Code à 6 chiffres", "en": "6-digit code",
        "de": "6-stelliger Code", "es": "Código de 6 dígitos",
        "it": "Codice a 6 cifre", "pt": "Código de 6 dígitos",
        "nl": "6-cijferige code", "zh": "6 位验证码",
    },
    "totp_confirm_btn": {
        "fr": "Confirmer", "en": "Confirm",
        "de": "Bestätigen", "es": "Confirmar",
        "it": "Conferma", "pt": "Confirmar",
        "nl": "Bevestigen", "zh": "确认",
    },
    "totp_wrong": {
        "fr": "Code incorrect. Vérifiez que l'heure de votre téléphone est correcte.",
        "en": "Incorrect code. Make sure your phone's time is correct.",
        "de": "Falscher Code. Überprüfen Sie, ob die Uhrzeit Ihres Telefons korrekt ist.",
        "es": "Código incorrecto. Asegúrese de que la hora de su teléfono sea correcta.",
        "it": "Codice errato. Assicurati che l'orario del tuo telefono sia corretto.",
        "pt": "Código incorreto. Verifique se a hora do seu telefone está correta.",
        "nl": "Onjuiste code. Controleer of de tijd op uw telefoon correct is.",
        "zh": "验证码错误。请确保您的手机时间正确。",
    },

    # ── TOTP verify ──
    "totp_verify_title": {
        "fr": "Vérification 2FA", "en": "2FA Verification",
        "de": "2FA-Verifizierung", "es": "Verificación 2FA",
        "it": "Verifica 2FA", "pt": "Verificação 2FA",
        "nl": "2FA-verificatie", "zh": "双因素认证",
    },
    "totp_account": {
        "fr": "Compte : **{username}**", "en": "Account: **{username}**",
        "de": "Konto: **{username}**", "es": "Cuenta: **{username}**",
        "it": "Account: **{username}**", "pt": "Conta: **{username}**",
        "nl": "Account: **{username}**", "zh": "账户：**{username}**",
    },
    "totp_verify_btn": {
        "fr": "Vérifier", "en": "Verify",
        "de": "Prüfen", "es": "Verificar",
        "it": "Verifica", "pt": "Verificar",
        "nl": "Verifiëren", "zh": "验证",
    },
    "totp_back_btn": {
        "fr": "← Retour", "en": "← Back",
        "de": "← Zurück", "es": "← Volver",
        "it": "← Indietro", "pt": "← Voltar",
        "nl": "← Terug", "zh": "← 返回",
    },
    "totp_verify_wrong": {
        "fr": "Code incorrect ou expiré. Réessayez.",
        "en": "Incorrect or expired code. Please try again.",
        "de": "Falscher oder abgelaufener Code. Bitte erneut versuchen.",
        "es": "Código incorrecto o expirado. Inténtelo de nuevo.",
        "it": "Codice errato o scaduto. Riprova.",
        "pt": "Código incorreto ou expirado. Tente novamente.",
        "nl": "Onjuiste of verlopen code. Probeer het opnieuw.",
        "zh": "验证码错误或已过期。请重试。",
    },

    # ── Charts / Dashboard ──
    "chart_pnl_name": {
        "fr": "P&L cumulé ($)", "en": "Cumulative P&L ($)",
        "de": "Kumuliertes P&L ($)", "es": "P&L acumulado ($)",
        "it": "P&L cumulato ($)", "pt": "P&L acumulado ($)",
        "nl": "Cumulatief P&L ($)", "zh": "累计盈亏 ($)",
    },
    "chart_btc_price": {
        "fr": "Prix BTC ($)", "en": "BTC Price ($)",
        "de": "BTC-Preis ($)", "es": "Precio BTC ($)",
        "it": "Prezzo BTC ($)", "pt": "Preço BTC ($)",
        "nl": "BTC-prijs ($)", "zh": "BTC 价格 ($)",
    },

    # ----------------------------------------------------------
    # FLUX MANAGER
    # ----------------------------------------------------------
    # Flux descriptions (partly French inside FLUX_DEFINITIONS)
    "col_asset": {
        "fr": "Actif", "en": "Asset",
        "de": "Vermögenswert", "es": "Activo",
        "it": "Asset", "pt": "Ativo",
        "nl": "Actief", "zh": "资产",
    },
    "col_size_usd": {
        "fr": "Taille", "en": "Size",
        "de": "Größe", "es": "Tamaño",
        "it": "Dimensione", "pt": "Tamanho",
        "nl": "Grootte", "zh": "规模",
    },
    # ── Global overview table ───────────────────────────────────────────────
    "logs_lines_pages": {
        "fr": "{n} lignes · {p} page{ps}",
        "en": "{n} rows · {p} page{ps}",
        "de": "{n} Zeilen · {p} Seite{ps}",
        "es": "{n} líneas · {p} página{ps}",
        "it": "{n} righe · {p} pagina{ps}",
        "pt": "{n} linhas · {p} página{ps}",
        "nl": "{n} rijen · {p} pagina{ps}",
        "zh": "{n} 行 · {p} 页",
    },
    # ── Asset status badges ─────────────────────────────────────────────────
    # ── Decision dialog ─────────────────────────────────────────────────────
    "dialog_old_trade": {
        "fr": "⚠️ Trade antérieur à l'audit trail (13/04/2026) — seule l'explication IA est disponible.",
        "en": "⚠️ Trade predates audit trail (13/04/2026) — only the AI explanation is available.",
        "de": "⚠️ Trade vor dem Audit-Trail (13.04.2026) — nur die KI-Erklärung verfügbar.",
        "es": "⚠️ Trade anterior al audit trail (13/04/2026) — solo está disponible la explicación IA.",
        "it": "⚠️ Trade precedente all'audit trail (13/04/2026) — disponibile solo la spiegazione AI.",
        "pt": "⚠️ Trade anterior ao audit trail (13/04/2026) — apenas a explicação IA está disponível.",
        "nl": "⚠️ Trade voorafgaand aan audit trail (13/04/2026) — alleen de AI-uitleg beschikbaar.",
        "zh": "⚠️ 该交易在审计追踪(2026/04/13)之前 — 仅 AI 解释可用。",
    },
    "tab_formula": {
        "fr": "🧮 Formule", "en": "🧮 Formula",
        "de": "🧮 Formel", "es": "🧮 Fórmula",
        "it": "🧮 Formula", "pt": "🧮 Fórmula",
        "nl": "🧮 Formule", "zh": "🧮 公式",
    },
    "tab_agents_dialog": {
        "fr": "🤖 Agents", "en": "🤖 Agents",
        "de": "🤖 Agenten", "es": "🤖 Agentes",
        "it": "🤖 Agenti", "pt": "🤖 Agentes",
        "nl": "🤖 Agenten", "zh": "🤖 代理人",
    },
    "tab_market_dialog": {
        "fr": "📈 Marché", "en": "📈 Market",
        "de": "📈 Markt", "es": "📈 Mercado",
        "it": "📈 Mercato", "pt": "📈 Mercado",
        "nl": "📈 Markt", "zh": "📈 市场",
    },
    "tab_decision": {
        "fr": "⚖️ Décision", "en": "⚖️ Decision",
        "de": "⚖️ Entscheidung", "es": "⚖️ Decisión",
        "it": "⚖️ Decisione", "pt": "⚖️ Decisão",
        "nl": "⚖️ Beslissing", "zh": "⚖️ 决策",
    },
    "tab_ai": {
        "fr": "🧠 IA", "en": "🧠 AI",
        "de": "🧠 KI", "es": "🧠 IA",
        "it": "🧠 IA", "pt": "🧠 IA",
        "nl": "🧠 AI", "zh": "🧠 AI",
    },
    # ── Profile labels ──────────────────────────────────────────────────────

    # ── Memory tab ──────────────────────────────────────────────────────────

    # ── Meta-analysis tab ───────────────────────────────────────────────────

    # ── Per-asset tab ────────────────────────────────────────────────────────

    # ── Backup tab ───────────────────────────────────────────────────────────
    "bkp_title": {
        "fr": "Sauvegarde & Restauration de la configuration",
        "en": "Configuration Backup & Restore",
        "de": "Konfigurationssicherung & -wiederherstellung",
        "es": "Copia de seguridad y restauración de la configuración",
        "it": "Backup e ripristino della configurazione",
        "pt": "Backup e restauração da configuração",
        "nl": "Configuratieback-up en -herstel",
        "zh": "配置备份与恢复",
    },
    "bkp_info": {
        "fr": "⚠️ La sauvegarde inclut **settings.yaml** et tous les fichiers **config/assets/*.yaml**.",
        "en": "⚠️ The backup includes **settings.yaml** and all **config/assets/*.yaml** files.",
        "de": "⚠️ Die Sicherung enthält **settings.yaml** und alle **config/assets/*.yaml**-Dateien.",
        "es": "⚠️ La copia de seguridad incluye **settings.yaml** y todos los archivos **config/assets/*.yaml**.",
        "it": "⚠️ Il backup include **settings.yaml** e tutti i file **config/assets/*.yaml**.",
        "pt": "⚠️ O backup inclui **settings.yaml** e todos os arquivos **config/assets/*.yaml**.",
        "nl": "⚠️ De back-up bevat **settings.yaml** en alle **config/assets/*.yaml**-bestanden.",
        "zh": "⚠️ 备份包含 **settings.yaml** 以及所有 **config/assets/*.yaml** 文件。",
    },
    "bkp_export_title": {
        "fr": "📤 Exporter", "en": "📤 Export",
        "de": "📤 Exportieren", "es": "📤 Exportar",
        "it": "📤 Esporta", "pt": "📤 Exportar",
        "nl": "📤 Exporteren", "zh": "📤 导出",
    },
    "bkp_export_caption": {
        "fr": "Télécharge un fichier ZIP contenant toute la configuration actuelle.",
        "en": "Downloads a ZIP file containing the full current configuration.",
        "de": "Lädt eine ZIP-Datei mit der vollständigen aktuellen Konfiguration herunter.",
        "es": "Descarga un archivo ZIP con toda la configuración actual.",
        "it": "Scarica un file ZIP contenente tutta la configurazione attuale.",
        "pt": "Baixa um arquivo ZIP com toda a configuração atual.",
        "nl": "Downloadt een ZIP-bestand met de volledige huidige configuratie.",
        "zh": "下载包含完整当前配置的ZIP文件。",
    },
    "bkp_download_btn": {
        "fr": "⬇️ Télécharger la configuration", "en": "⬇️ Download configuration",
        "de": "⬇️ Konfiguration herunterladen", "es": "⬇️ Descargar configuración",
        "it": "⬇️ Scarica configurazione", "pt": "⬇️ Baixar configuração",
        "nl": "⬇️ Configuratie downloaden", "zh": "⬇️ 下载配置",
    },
    "bkp_ready": {
        "fr": "ZIP prêt — {n} Ko", "en": "ZIP ready — {n} KB",
        "de": "ZIP bereit — {n} KB", "es": "ZIP listo — {n} KB",
        "it": "ZIP pronto — {n} KB", "pt": "ZIP pronto — {n} KB",
        "nl": "ZIP klaar — {n} KB", "zh": "ZIP就绪 — {n} KB",
    },
    "bkp_export_error": {
        "fr": "❌ Erreur export :", "en": "❌ Export error:",
        "de": "❌ Exportfehler:", "es": "❌ Error de exportación:",
        "it": "❌ Errore esportazione:", "pt": "❌ Erro de exportação:",
        "nl": "❌ Exportfout:", "zh": "❌ 导出错误:",
    },
    "bkp_import_title": {
        "fr": "📥 Importer / Restaurer", "en": "📥 Import / Restore",
        "de": "📥 Importieren / Wiederherstellen", "es": "📥 Importar / Restaurar",
        "it": "📥 Importa / Ripristina", "pt": "📥 Importar / Restaurar",
        "nl": "📥 Importeren / Herstellen", "zh": "📥 导入 / 恢复",
    },
    "bkp_import_caption": {
        "fr": "Restaure la configuration depuis un ZIP exporté précédemment. L'état actuel est sauvegardé automatiquement avant toute écrasure.",
        "en": "Restores the configuration from a previously exported ZIP. The current state is automatically backed up before any overwrite.",
        "de": "Stellt die Konfiguration aus einem zuvor exportierten ZIP wieder her. Der aktuelle Zustand wird vor dem Überschreiben automatisch gesichert.",
        "es": "Restaura la configuración desde un ZIP exportado anteriormente. El estado actual se guarda automáticamente antes de cualquier sobrescritura.",
        "it": "Ripristina la configurazione da un ZIP esportato in precedenza. Lo stato attuale viene salvato automaticamente prima di qualsiasi sovrascrittura.",
        "pt": "Restaura a configuração a partir de um ZIP exportado anteriormente. O estado atual é salvo automaticamente antes de qualquer substituição.",
        "nl": "Herstelt de configuratie vanuit een eerder geëxporteerde ZIP. De huidige staat wordt automatisch opgeslagen voor overschrijven.",
        "zh": "从之前导出的ZIP恢复配置。覆盖前自动备份当前状态。",
    },
    "bkp_choose_file": {
        "fr": "Choisir un fichier ZIP", "en": "Choose a ZIP file",
        "de": "ZIP-Datei auswählen", "es": "Elegir un archivo ZIP",
        "it": "Scegli un file ZIP", "pt": "Escolher um arquivo ZIP",
        "nl": "Kies een ZIP-bestand", "zh": "选择ZIP文件",
    },
    "bkp_confirm_check": {
        "fr": "⚠️ Je confirme vouloir écraser la configuration actuelle",
        "en": "⚠️ I confirm I want to overwrite the current configuration",
        "de": "⚠️ Ich bestätige, die aktuelle Konfiguration überschreiben zu wollen",
        "es": "⚠️ Confirmo que deseo sobrescribir la configuración actual",
        "it": "⚠️ Confermo di voler sovrascrivere la configurazione attuale",
        "pt": "⚠️ Confirmo que desejo substituir a configuração atual",
        "nl": "⚠️ Ik bevestig de huidige configuratie te willen overschrijven",
        "zh": "⚠️ 我确认要覆盖当前配置",
    },
    "bkp_restore_btn": {
        "fr": "🔄 Restaurer depuis ce ZIP", "en": "🔄 Restore from this ZIP",
        "de": "🔄 Aus diesem ZIP wiederherstellen", "es": "🔄 Restaurar desde este ZIP",
        "it": "🔄 Ripristina da questo ZIP", "pt": "🔄 Restaurar a partir deste ZIP",
        "nl": "🔄 Herstellen vanuit dit ZIP", "zh": "🔄 从此ZIP恢复",
    },
    "bkp_restore_success": {
        "fr": "✅ {n} fichier(s) restauré(s)", "en": "✅ {n} file(s) restored",
        "de": "✅ {n} Datei(en) wiederhergestellt", "es": "✅ {n} archivo(s) restaurado(s)",
        "it": "✅ {n} file ripristinato/i", "pt": "✅ {n} arquivo(s) restaurado(s)",
        "nl": "✅ {n} bestand(en) hersteld", "zh": "✅ 已恢复 {n} 个文件",
    },
    "bkp_backup_path": {
        "fr": "💾 Sauvegarde auto :", "en": "💾 Auto backup:",
        "de": "💾 Automatische Sicherung:", "es": "💾 Copia automática:",
        "it": "💾 Backup automatico:", "pt": "💾 Backup automático:",
        "nl": "💾 Automatische back-up:", "zh": "💾 自动备份:",
    },
    "bkp_restart_info": {
        "fr": "🔄 Redémarrez le daemon pour appliquer les nouveaux paramètres.",
        "en": "🔄 Restart the daemon to apply the new parameters.",
        "de": "🔄 Daemon neu starten, um die neuen Parameter anzuwenden.",
        "es": "🔄 Reinicie el daemon para aplicar los nuevos parámetros.",
        "it": "🔄 Riavvia il daemon per applicare i nuovi parametri.",
        "pt": "🔄 Reinicie o daemon para aplicar os novos parâmetros.",
        "nl": "🔄 Herstart de daemon om de nieuwe parameters toe te passen.",
        "zh": "🔄 重启守护进程以应用新参数。",
    },
    "bkp_restore_error": {
        "fr": "❌ Restauration échouée :", "en": "❌ Restore failed:",
        "de": "❌ Wiederherstellung fehlgeschlagen:", "es": "❌ Restauración fallida:",
        "it": "❌ Ripristino fallito:", "pt": "❌ Restauração falhou:",
        "nl": "❌ Herstel mislukt:", "zh": "❌ 恢复失败:",
    },
    "bkp_list_title": {
        "fr": "📂 Sauvegardes automatiques disponibles", "en": "📂 Available automatic backups",
        "de": "📂 Verfügbare automatische Sicherungen", "es": "📂 Copias de seguridad automáticas disponibles",
        "it": "📂 Backup automatici disponibili", "pt": "📂 Backups automáticos disponíveis",
        "nl": "📂 Beschikbare automatische back-ups", "zh": "📂 可用的自动备份",
    },
    "bkp_no_backups": {
        "fr": "Aucune sauvegarde disponible pour l'instant.",
        "en": "No backup available yet.",
        "de": "Noch keine Sicherung verfügbar.",
        "es": "Aún no hay copias de seguridad disponibles.",
        "it": "Nessun backup disponibile per ora.",
        "pt": "Nenhum backup disponível ainda.",
        "nl": "Nog geen back-up beschikbaar.",
        "zh": "暂无可用备份。",
    },
    "bkp_list_error": {
        "fr": "Impossible de lister les sauvegardes :", "en": "Unable to list backups:",
        "de": "Sicherungen können nicht aufgelistet werden:", "es": "No se pueden listar las copias de seguridad:",
        "it": "Impossibile elencare i backup:", "pt": "Não é possível listar os backups:",
        "nl": "Kan back-ups niet weergeven:", "zh": "无法列出备份:",
    },
    "bkp_restore_from": {
        "fr": "✅ {n} fichier(s) restauré(s) depuis {filename}",
        "en": "✅ {n} file(s) restored from {filename}",
        "de": "✅ {n} Datei(en) aus {filename} wiederhergestellt",
        "es": "✅ {n} archivo(s) restaurado(s) desde {filename}",
        "it": "✅ {n} file ripristinato/i da {filename}",
        "pt": "✅ {n} arquivo(s) restaurado(s) de {filename}",
        "nl": "✅ {n} bestand(en) hersteld vanuit {filename}",
        "zh": "✅ 已从 {filename} 恢复 {n} 个文件",
    },
    # ── Quant dashboard ──────────────────────────────────────────────────────
    # ── Sidebar section headers ───────────────────────────────────────────────
    # ── Admin tab labels ──────────────────────────────────────────────────────
    # ── Flux Manager — categories ───────────────────────────────────────────
    # ── Flux Manager — step descriptions ────────────────────────────────────
    # ── Flux Manager labels (resolved via t() in render_status_board) ──────────
    # ── Flux Manager controls (render_controls) ───────────────────────────────
    # ── Quant Engine tab (streamlit_app.py) ───────────────────────────────────
    # ── multi_asset.py ─────────────────────────────────────────────────────────
    # ── auth.py ───────────────────────────────────────────────────────────────
    "auth_save_changes": {
        "fr": "💾 Sauvegarder les modifications", "en": "💾 Save changes",
        "de": "💾 Änderungen speichern", "es": "💾 Guardar cambios",
        "it": "💾 Salva modifiche", "pt": "💾 Guardar alterações",
        "nl": "💾 Wijzigingen opslaan", "zh": "💾 保存更改",
    },
    # ── Reset page (streamlit_app.py) ─────────────────────────────────────────
    # ── Live metrics (streamlit_app.py) ───────────────────────────────────────

    # ── V7 Dashboard — Trade table & Admin ──────────────────────────────────
    "col_sl": {"fr": "SL", "en": "SL", "de": "SL", "es": "SL", "it": "SL", "pt": "SL", "nl": "SL", "zh": "止损"},
    "col_tp": {"fr": "TP", "en": "TP", "de": "TP", "es": "TP", "it": "TP", "pt": "TP", "nl": "TP", "zh": "止盈"},
    "col_progression": {"fr": "Progression", "en": "Progress", "de": "Fortschritt", "es": "Progreso", "it": "Progresso", "pt": "Progresso", "nl": "Voortgang", "zh": "进度"},
    "col_status": {"fr": "Statut", "en": "Status", "de": "Status", "es": "Estado", "it": "Stato", "pt": "Status", "nl": "Status", "zh": "状态"},
    "col_dag": {"fr": "DAG", "en": "DAG", "de": "DAG", "es": "DAG", "it": "DAG", "pt": "DAG", "nl": "DAG", "zh": "DAG"},
    "col_signal": {"fr": "Signal", "en": "Signal", "de": "Signal", "es": "Señal", "it": "Segnale", "pt": "Sinal", "nl": "Signaal", "zh": "信号"},
    "col_run": {"fr": "Run", "en": "Run", "de": "Lauf", "es": "Run", "it": "Run", "pt": "Run", "nl": "Run", "zh": "运行"},
    "col_carry": {"fr": "Carry", "en": "Carry", "de": "Carry", "es": "Carry", "it": "Carry", "pt": "Carry", "nl": "Carry", "zh": "套利"},
    "col_return": {"fr": "Rendement", "en": "Return", "de": "Rendite", "es": "Rendimiento", "it": "Rendimento", "pt": "Retorno", "nl": "Rendement", "zh": "收益率"},
    "global_view_title": {"fr": "Vue Globale — Funding Carry", "en": "Global View — Funding Carry", "de": "Globalansicht — Funding Carry", "es": "Vista Global — Funding Carry", "it": "Vista Globale — Funding Carry", "pt": "Visão Global — Funding Carry", "nl": "Globaal Overzicht — Funding Carry", "zh": "全局视图 — 资金费率套利"},
    "trades_all_title": {"fr": "Historique des trades — tous actifs", "en": "Trade History — All Assets", "de": "Handelshistorie — Alle", "es": "Historial — Todos", "it": "Storico — Tutti", "pt": "Histórico — Todos", "nl": "Handelsgeschiedenis — Alle", "zh": "交易历史 — 全部"},
    "tab_carry_cfg": {"fr": "Actifs Carry", "en": "Carry Assets", "de": "Carry-Assets", "es": "Activos Carry", "it": "Asset Carry", "pt": "Ativos Carry", "nl": "Carry-Activa", "zh": "套利资产"},
    # ── Carry Config labels ──
    "carry_cfg_subtitle": {
        "fr": "Activez/désactivez les actifs et ajustez leurs paramètres. Les modifications sont sauvegardées dans `config/carry_assets.yaml`.",
        "en": "Enable/disable assets and adjust their parameters. Changes are saved to `config/carry_assets.yaml`.",
        "de": "Aktivieren/deaktivieren Sie Assets und passen Sie deren Parameter an. Änderungen werden in `config/carry_assets.yaml` gespeichert.",
        "es": "Active/desactive activos y ajuste sus parámetros. Los cambios se guardan en `config/carry_assets.yaml`.",
        "it": "Attiva/disattiva gli asset e regola i parametri. Le modifiche sono salvate in `config/carry_assets.yaml`.",
        "pt": "Ative/desative ativos e ajuste seus parâmetros. As alterações são salvas em `config/carry_assets.yaml`.",
        "nl": "Activeer/deactiveer activa en pas parameters aan. Wijzigingen worden opgeslagen in `config/carry_assets.yaml`.",
        "zh": "启用/禁用资产并调整参数。更改保存到 `config/carry_assets.yaml`。",
    },
    "carry_global_params": {"fr": "🌐 Paramètres globaux", "en": "🌐 Global Parameters", "de": "🌐 Globale Parameter", "es": "🌐 Parámetros globales", "it": "🌐 Parametri globali", "pt": "🌐 Parâmetros globais", "nl": "🌐 Globale parameters", "zh": "🌐 全局参数"},
    "carry_total_capital": {"fr": "Capital total ($)", "en": "Total capital ($)", "de": "Gesamtkapital ($)", "es": "Capital total ($)", "it": "Capitale totale ($)", "pt": "Capital total ($)", "nl": "Totaal kapitaal ($)", "zh": "总资金 ($)"},
    "carry_max_exposure": {"fr": "Exposition max (% capital)", "en": "Max exposure (% capital)", "de": "Max. Exposure (% Kapital)", "es": "Exposición máx. (% capital)", "it": "Esposizione max (% capitale)", "pt": "Exposição máx. (% capital)", "nl": "Max blootstelling (% kapitaal)", "zh": "最大敞口 (% 资金)"},
    "carry_max_positions": {"fr": "Max positions simultanées", "en": "Max simultaneous positions", "de": "Max gleichzeitige Positionen", "es": "Máx. posiciones simultáneas", "it": "Max posizioni simultanee", "pt": "Máx. posições simultâneas", "nl": "Max gelijktijdige posities", "zh": "最大同时持仓"},
    "carry_roundtrip_cost": {"fr": "Coût round-trip (bps)", "en": "Round-trip cost (bps)", "de": "Round-Trip-Kosten (bps)", "es": "Coste ida y vuelta (bps)", "it": "Costo round-trip (bps)", "pt": "Custo ida e volta (bps)", "nl": "Round-trip kosten (bps)", "zh": "往返成本 (bps)"},
    "carry_hold_days": {"fr": "Hold estimé (jours)", "en": "Estimated hold (days)", "de": "Geschätzte Haltedauer (Tage)", "es": "Duración estimada (días)", "it": "Hold stimato (giorni)", "pt": "Duração estimada (dias)", "nl": "Geschatte hold (dagen)", "zh": "预计持有 (天)"},
    "carry_save_global_btn": {"fr": "💾 Sauvegarder paramètres globaux", "en": "💾 Save global parameters", "de": "💾 Globale Parameter speichern", "es": "💾 Guardar parámetros globales", "it": "💾 Salva parametri globali", "pt": "💾 Salvar parâmetros globais", "nl": "💾 Globale parameters opslaan", "zh": "💾 保存全局参数"},
    "carry_save_global_ok": {"fr": "✅ Paramètres globaux sauvegardés.", "en": "✅ Global parameters saved.", "de": "✅ Globale Parameter gespeichert.", "es": "✅ Parámetros globales guardados.", "it": "✅ Parametri globali salvati.", "pt": "✅ Parâmetros globais salvos.", "nl": "✅ Globale parameters opgeslagen.", "zh": "✅ 全局参数已保存。"},
    "carry_configured_assets": {"fr": "Actifs configurés", "en": "Configured Assets", "de": "Konfigurierte Assets", "es": "Activos configurados", "it": "Asset configurati", "pt": "Ativos configurados", "nl": "Geconfigureerde activa", "zh": "已配置资产"},
    "carry_enabled": {"fr": "Activé", "en": "Enabled", "de": "Aktiviert", "es": "Activado", "it": "Attivato", "pt": "Ativado", "nl": "Ingeschakeld", "zh": "已启用"},
    "carry_capital": {"fr": "Capital ($)", "en": "Capital ($)", "de": "Kapital ($)", "es": "Capital ($)", "it": "Capitale ($)", "pt": "Capital ($)", "nl": "Kapitaal ($)", "zh": "资金 ($)"},
    "carry_fraction": {"fr": "Fraction", "en": "Fraction", "de": "Anteil", "es": "Fracción", "it": "Frazione", "pt": "Fração", "nl": "Fractie", "zh": "比例"},
    "carry_safety_cap": {"fr": "Safety cap ($)", "en": "Safety cap ($)", "de": "Sicherheitslimit ($)", "es": "Límite seguridad ($)", "it": "Safety cap ($)", "pt": "Limite segurança ($)", "nl": "Veiligheidslimiet ($)", "zh": "安全上限 ($)"},
    "carry_stress_loss": {"fr": "Stress loss (%)", "en": "Stress loss (%)", "de": "Stressverlust (%)", "es": "Pérdida estrés (%)", "it": "Stress loss (%)", "pt": "Perda estresse (%)", "nl": "Stressverlies (%)", "zh": "压力损失 (%)"},
    "carry_leverage": {"fr": "Levier", "en": "Leverage", "de": "Hebel", "es": "Apalancamiento", "it": "Leva", "pt": "Alavancagem", "nl": "Hefboom", "zh": "杠杆"},
    "carry_min_funding": {"fr": "Funding min (%/8h)", "en": "Min funding (%/8h)", "de": "Min. Funding (%/8h)", "es": "Funding mín. (%/8h)", "it": "Funding min (%/8h)", "pt": "Funding mín. (%/8h)", "nl": "Min funding (%/8h)", "zh": "最低资金费率 (%/8h)"},
    "carry_max_hold": {"fr": "Max hold (jours)", "en": "Max hold (days)", "de": "Max Haltedauer (Tage)", "es": "Duración máx. (días)", "it": "Max hold (giorni)", "pt": "Duração máx. (dias)", "nl": "Max hold (dagen)", "zh": "最长持有 (天)"},
    "carry_exit_hours": {"fr": "Exit funding nég (h)", "en": "Exit neg. funding (h)", "de": "Exit neg. Funding (h)", "es": "Salida fund. neg. (h)", "it": "Exit funding neg (h)", "pt": "Saída fund. neg. (h)", "nl": "Exit neg. funding (u)", "zh": "负费率退出 (小时)"},
    "carry_save_asset_btn": {"fr": "💾 Sauvegarder", "en": "💾 Save", "de": "💾 Speichern", "es": "💾 Guardar", "it": "💾 Salva", "pt": "💾 Salvar", "nl": "💾 Opslaan", "zh": "💾 保存"},
    "carry_save_asset_ok": {"fr": "✅ {sym} sauvegardé.", "en": "✅ {sym} saved.", "de": "✅ {sym} gespeichert.", "es": "✅ {sym} guardado.", "it": "✅ {sym} salvato.", "pt": "✅ {sym} salvo.", "nl": "✅ {sym} opgeslagen.", "zh": "✅ {sym} 已保存。"},
    "carry_active_count": {"fr": "Actifs activés", "en": "Active assets", "de": "Aktive Assets", "es": "Activos activos", "it": "Asset attivi", "pt": "Ativos ativos", "nl": "Actieve activa", "zh": "已启用资产"},
    "carry_no_assets": {
        "fr": "⚠️ Aucun actif trouvé dans `config/carry_assets.yaml`. Le fichier est-il déployé sur le serveur ?",
        "en": "⚠️ No assets found in `config/carry_assets.yaml`. Is the file deployed on the server?",
        "de": "⚠️ Keine Assets in `config/carry_assets.yaml` gefunden. Ist die Datei auf dem Server bereitgestellt?",
        "es": "⚠️ No se encontraron activos en `config/carry_assets.yaml`. ¿Está el archivo desplegado en el servidor?",
        "it": "⚠️ Nessun asset trovato in `config/carry_assets.yaml`. Il file è deployato sul server?",
        "pt": "⚠️ Nenhum ativo encontrado em `config/carry_assets.yaml`. O arquivo está implantado no servidor?",
        "nl": "⚠️ Geen activa gevonden in `config/carry_assets.yaml`. Is het bestand op de server geïmplementeerd?",
        "zh": "⚠️ 在 `config/carry_assets.yaml` 中未找到资产。文件是否已部署到服务器？",
    },
    "carry_dag_hint": {
        "fr": "💡 Les DAGs sont créés uniquement pour les actifs activés. Les modifications prennent effet au prochain redémarrage de l'API.",
        "en": "💡 DAGs are created only for enabled assets. Changes take effect on next API restart.",
        "de": "💡 DAGs werden nur für aktivierte Assets erstellt. Änderungen werden beim nächsten API-Neustart wirksam.",
        "es": "💡 Los DAGs se crean solo para activos habilitados. Los cambios surten efecto al reiniciar la API.",
        "it": "💡 I DAG vengono creati solo per gli asset abilitati. Le modifiche hanno effetto al prossimo riavvio dell'API.",
        "pt": "💡 DAGs são criados apenas para ativos habilitados. As alterações entram em vigor na próxima reinicialização da API.",
        "nl": "💡 DAGs worden alleen aangemaakt voor ingeschakelde activa. Wijzigingen worden actief bij volgende API-herstart.",
        "zh": "💡 仅为已启用资产生成DAG。更改在下次API重启后生效。",
    },
    # ── Scanner labels ──
    "carry_scan_btn": {"fr": "🔄 Scanner Binance", "en": "🔄 Scan Binance", "de": "🔄 Binance scannen", "es": "🔄 Escanear Binance", "it": "🔄 Scansiona Binance", "pt": "🔄 Escanear Binance", "nl": "🔄 Binance scannen", "zh": "🔄 扫描币安"},
    "carry_scan_help": {
        "fr": "Détecte automatiquement tous les couples Spot/Perp éligibles",
        "en": "Automatically detects all eligible Spot/Perp pairs",
        "de": "Erkennt automatisch alle geeigneten Spot/Perp-Paare",
        "es": "Detecta automáticamente todos los pares Spot/Perp elegibles",
        "it": "Rileva automaticamente tutte le coppie Spot/Perp eleggibili",
        "pt": "Detecta automaticamente todos os pares Spot/Perp elegíveis",
        "nl": "Detecteert automatisch alle in aanmerking komende Spot/Perp-paren",
        "zh": "自动检测所有符合条件的现货/永续合约对",
    },
    "carry_scanning": {
        "fr": "Scan de l'univers Binance Spot ∩ Perp...",
        "en": "Scanning Binance Spot ∩ Perp universe...",
        "de": "Scanne Binance Spot ∩ Perp Universum...",
        "es": "Escaneando universo Binance Spot ∩ Perp...",
        "it": "Scansione universo Binance Spot ∩ Perp...",
        "pt": "Escaneando universo Binance Spot ∩ Perp...",
        "nl": "Scannen van Binance Spot ∩ Perp universum...",
        "zh": "正在扫描币安现货∩永续合约...",
    },
    "carry_scan_ok": {
        "fr": "✅ Univers mis à jour !",
        "en": "✅ Universe updated!",
        "de": "✅ Universum aktualisiert!",
        "es": "✅ ¡Universo actualizado!",
        "it": "✅ Universo aggiornato!",
        "pt": "✅ Universo atualizado!",
        "nl": "✅ Universum bijgewerkt!",
        "zh": "✅ 交易 universe 已更新！",
    },
    "carry_scan_error": {
        "fr": "Scan échoué",
        "en": "Scan failed",
        "de": "Scan fehlgeschlagen",
        "es": "Escaneo fallido",
        "it": "Scansione fallita",
        "pt": "Escaneamento falhou",
        "nl": "Scan mislukt",
        "zh": "扫描失败",
    },
    "carry_scan_last": {
        "fr": "🔍 Dernier scan : {n} actifs éligibles (sur {t} paires spot)",
        "en": "🔍 Last scan: {n} eligible assets (out of {t} spot pairs)",
        "de": "🔍 Letzter Scan: {n} geeignete Assets (von {t} Spot-Paaren)",
        "es": "🔍 Último escaneo: {n} activos elegibles (de {t} pares spot)",
        "it": "🔍 Ultima scansione: {n} asset eleggibili (su {t} coppie spot)",
        "pt": "🔍 Último escaneamento: {n} ativos elegíveis (de {t} pares spot)",
        "nl": "🔍 Laatste scan: {n} geschikte activa (uit {t} spot-paren)",
        "zh": "🔍 最近扫描：{n} 个合格资产（共 {t} 个现货对）",
    },
    # ── UI labels ──
    "carry_locked": {"fr": "🔒 Figé", "en": "🔒 Locked", "de": "🔒 Fixiert", "es": "🔒 Fijado", "it": "🔒 Bloccato", "pt": "🔒 Fixo", "nl": "🔒 Vast", "zh": "🔒 锁定"},
    "carry_locked_help": {
        "fr": "Protège la config contre l'optimisation automatique",
        "en": "Protects config from automatic optimization",
        "de": "Schützt Konfiguration vor automatischer Optimierung",
        "es": "Protege la configuración de la optimización automática",
        "it": "Protegge la configurazione dall'ottimizzazione automatica",
        "pt": "Protege a configuração da otimização automática",
        "nl": "Beschermt configuratie tegen automatische optimalisatie",
        "zh": "保护配置不被自动优化覆盖",
    },
    "carry_logo": {"fr": "📷 Logo", "en": "📷 Logo", "de": "📷 Logo", "es": "📷 Logo", "it": "📷 Logo", "pt": "📷 Logo", "nl": "📷 Logo", "zh": "📷 图标"},
    "carry_logo_help": {
        "fr": "Logo officiel 16×16 — sauvegardé localement",
        "en": "Official 16×16 logo — saved locally",
        "de": "Offizielles 16×16 Logo — lokal gespeichert",
        "es": "Logo oficial 16×16 — guardado localmente",
        "it": "Logo ufficiale 16×16 — salvato localmente",
        "pt": "Logo oficial 16×16 — salvo localmente",
        "nl": "Officieel 16×16 logo — lokaal opgeslagen",
        "zh": "官方16×16图标 — 本地保存",
    },
    "carry_expand_all": {"fr": "📂 Expand all", "en": "📂 Expand all", "de": "📂 Alle ausklappen", "es": "📂 Expandir todo", "it": "📂 Espandi tutto", "pt": "📂 Expandir tudo", "nl": "📂 Alles uitklappen", "zh": "📂 全部展开"},
    "carry_collapse_all": {"fr": "📁 Collapse all", "en": "📁 Collapse all", "de": "📁 Alle einklappen", "es": "📁 Colapsar todo", "it": "📁 Comprimi tutto", "pt": "📁 Recolher tudo", "nl": "📁 Alles inklappen", "zh": "📁 全部折叠"},
    "carry_optimize_btn": {
        "fr": "📊 Optimize", "en": "📊 Optimize", "de": "📊 Optimieren", "es": "📊 Optimizar", "it": "📊 Ottimizza", "pt": "📊 Otimizar", "nl": "📊 Optimaliseren", "zh": "📊 优化",
    },
    "carry_optimize_help": {
        "fr": "⚠️ Prérequis : lancer le backtest d'abord (🧪 Backtest → ALL → 365j). Lit les résultats et calcule les paramètres optimisés.",
        "en": "⚠️ Prerequisite: run backtest first (🧪 Backtest → ALL → 365d). Reads results and computes optimized parameters.",
        "de": "⚠️ Voraussetzung: erst Backtest laufen lassen. Liest Ergebnisse und berechnet optimierte Parameter.",
        "es": "⚠️ Requisito: ejecutar backtest primero. Lee resultados y calcula parámetros optimizados.",
        "it": "⚠️ Prerequisito: eseguire prima il backtest. Legge i risultati e calcola i parametri ottimizzati.",
        "pt": "⚠️ Pré-requisito: executar backtest primeiro. Lê resultados e calcula parâmetros otimizados.",
        "nl": "⚠️ Vereiste: eerst backtest uitvoeren. Leest resultaten en berekent geoptimaliseerde parameters.",
        "zh": "⚠️ 先决条件：先运行回测。读取结果并计算优化参数。",
    },
    "carry_disable_btn": {
        "fr": "🛑 Désactiver les {n}", "en": "🛑 Disable {n}", "de": "🛑 {n} deaktivieren", "es": "🛑 Desactivar {n}", "it": "🛑 Disattiva {n}", "pt": "🛑 Desativar {n}", "nl": "🛑 {n} uitschakelen", "zh": "🛑 禁用{n}个",
    },
    "carry_optimize_prerequisite": {
        "fr": "📊 **Optimize** nécessite un backtest préalable (🧪 Backtest → ALL → 365j). Il lit les résultats et calcule les paramètres optimisés par actif.",
        "en": "📊 **Optimize** requires a backtest first (🧪 Backtest → ALL → 365d). It reads results and computes optimized per-asset parameters.",
        "de": "📊 **Optimize** erfordert zuerst einen Backtest. Liest Ergebnisse und berechnet optimierte Parameter pro Asset.",
        "es": "📊 **Optimize** requiere un backtest previo. Lee resultados y calcula parámetros optimizados por activo.",
        "it": "📊 **Optimize** richiede prima un backtest. Legge i risultati e calcola parametri ottimizzati per asset.",
        "pt": "📊 **Optimize** requer um backtest primeiro. Lê resultados e calcula parâmetros otimizados por ativo.",
        "nl": "📊 **Optimize** vereist eerst een backtest. Leest resultaten en berekent geoptimaliseerde parameters per activa.",
        "zh": "📊 **优化** 需要先运行回测。读取结果并计算每个资产的优化参数。",
    },
    "carry_disabled_ok": {
        "fr": "{n} actifs désactivés — cliquez 'Apply & Reload DAGs' pour synchroniser",
        "en": "{n} assets disabled — click 'Apply & Reload DAGs' to sync",
        "de": "{n} Assets deaktiviert — 'Apply & Reload DAGs' zum Synchronisieren",
        "es": "{n} activos desactivados — clic 'Apply & Reload DAGs' para sincronizar",
        "it": "{n} asset disattivati — clicca 'Apply & Reload DAGs' per sincronizzare",
        "pt": "{n} ativos desativados — clique 'Apply & Reload DAGs' para sincronizar",
        "nl": "{n} activa uitgeschakeld — klik 'Apply & Reload DAGs' om te synchroniseren",
        "zh": "{n} 个资产已禁用 — 点击 'Apply & Reload DAGs' 同步",
    },
    "emergency_close_title": {"fr": "Fermeture d'urgence", "en": "Emergency Close", "de": "Not-Aus", "es": "Cierre de emergencia", "it": "Chiusura d'emergenza", "pt": "Fechamento de emergência", "nl": "Noodstop", "zh": "紧急平仓"},
    "emergency_close_caption": {"fr": "Ferme TOUTES les positions ouvertes au prix spot actuel.", "en": "Closes ALL open positions at current spot price.", "de": "Schließt ALLE offenen Positionen zum aktuellen Spot-Preis.", "es": "Cierra TODAS las posiciones abiertas al precio spot actual.", "it": "Chiude TUTTE le posizioni aperte al prezzo spot attuale.", "pt": "Fecha TODAS as posições abertas ao preço spot atual.", "nl": "Sluit ALLE open posities tegen de huidige spotprijs.", "zh": "以当前现货价格平仓所有持仓。"},
    "emergency_close_btn": {"fr": "Fermer les", "en": "Close", "de": "Schließen", "es": "Cerrar", "it": "Chiudi", "pt": "Fechar", "nl": "Sluiten", "zh": "平仓"},
    "no_transactions": {"fr": "Aucune transaction enregistrée.", "en": "No transactions recorded.", "de": "Keine Transaktionen aufgezeichnet.", "es": "Sin transacciones registradas.", "it": "Nessuna transazione registrata.", "pt": "Nenhuma transação registrada.", "nl": "Geen transacties geregistreerd.", "zh": "无交易记录。"},
    "closed_status": {"fr": "fermé", "en": "closed", "de": "geschlossen", "es": "cerrado", "it": "chiuso", "pt": "fechado", "nl": "gesloten", "zh": "已平仓"},
    "open_status": {"fr": "ouvert", "en": "open", "de": "offen", "es": "abierto", "it": "aperto", "pt": "aberto", "nl": "open", "zh": "持仓中"},

    "no_open_positions": {"fr": "Aucune position ouverte.", "en": "No open positions.", "de": "Keine offenen Positionen.", "es": "Sin posiciones abiertas.", "it": "Nessuna posizione aperta.", "pt": "Nenhuma posição aberta.", "nl": "Geen open posities.", "zh": "无持仓。"},
    "filter_action": {"fr": "Action", "en": "Action", "de": "Aktion", "es": "Acción", "it": "Azione", "pt": "Ação", "nl": "Actie", "zh": "操作"},
    "filter_status": {"fr": "Statut", "en": "Status", "de": "Status", "es": "Estado", "it": "Stato", "pt": "Status", "nl": "Status", "zh": "状态"},

    "history_title": {"fr": "Historique des Transactions", "en": "Transaction History", "de": "Transaktionsverlauf", "es": "Historial de Transacciones", "it": "Storico Transazioni", "pt": "Histórico de Transações", "nl": "Transactiegeschiedenis", "zh": "交易历史"},

    "live_price_title": {"fr": "Prix temps réel", "en": "Live Price", "de": "Live-Preis", "es": "Precio en vivo", "it": "Prezzo live", "pt": "Preço ao vivo", "nl": "Live prijs", "zh": "实时价格"},
    "trades_journal_title": {"fr": "Journal des trades", "en": "Trade Journal", "de": "Trade-Journal", "es": "Diario de operaciones", "it": "Registro operazioni", "pt": "Diário de operações", "nl": "Trade-logboek", "zh": "交易日志"},

    # ── Backtest & trade summary ─────────────────────────────────────────────
    "backtest_days_history": {
        "fr": "Jours d'historique", "en": "Days of history",
        "de": "Tage Historie", "es": "Días de historial",
        "it": "Giorni di storico", "pt": "Dias de histórico",
        "nl": "Dagen geschiedenis", "zh": "历史天数",
    },
    "trades_summary_line": {
        "fr": "TOTAL · {n} trades ({closed} fermés, {open} ouverts)",
        "en": "TOTAL · {n} trades ({closed} closed, {open} open)",
        "de": "TOTAL · {n} Trades ({closed} geschlossen, {open} offen)",
        "es": "TOTAL · {n} operaciones ({closed} cerradas, {open} abiertas)",
        "it": "TOTAL · {n} operazioni ({closed} chiuse, {open} aperte)",
        "pt": "TOTAL · {n} operações ({closed} fechadas, {open} abertas)",
        "nl": "TOTAL · {n} trades ({closed} gesloten, {open} open)",
        "zh": "总计 · {n} 笔交易 ({closed} 已平, {open} 持仓中)",
    },
    "backtest_run_btn": {
        "fr": "🚀 Lancer Backtest V7", "en": "🚀 Run V7 Backtest",
        "de": "🚀 V7 Backtest starten", "es": "🚀 Ejecutar Backtest V7",
        "it": "🚀 Avvia Backtest V7", "pt": "🚀 Executar Backtest V7",
        "nl": "🚀 V7 Backtest uitvoeren", "zh": "🚀 运行V7回测",
    },
    "backtest_scope_active": {
        "fr": "ALL — tous les actifs actifs", "en": "ALL — every active asset",
        "de": "ALL — alle aktiven Assets", "es": "ALL — todos los activos activos",
        "it": "ALL — tutti gli asset attivi", "pt": "ALL — todos os ativos ativos",
        "nl": "ALL — alle actieve assets", "zh": "ALL — 全部活跃资产",
    },
    "backtest_scope_all": {
        "fr": "ALL — tous les actifs déclarés", "en": "ALL — every declared asset",
        "de": "ALL — alle deklarierten Assets", "es": "ALL — todos los activos declarados",
        "it": "ALL — tutti gli asset dichiarati", "pt": "ALL — todos os ativos declarados",
        "nl": "ALL — alle gedeclareerde assets", "zh": "ALL — 全部已声明资产",
    },
    "backtest_scope_caption": {
        "fr": "{n} actifs seront testés, chacun avec ses propres paramètres carry_assets.yaml.",
        "en": "{n} assets will be tested, each with its own carry_assets.yaml settings.",
        "de": "{n} Assets werden getestet, jeweils mit eigenen carry_assets.yaml-Werten.",
        "es": "Se probarán {n} activos, cada uno con sus propios ajustes de carry_assets.yaml.",
        "it": "Verranno testati {n} asset, ciascuno con le proprie impostazioni carry_assets.yaml.",
        "pt": "Serão testados {n} ativos, cada um com as suas próprias definições carry_assets.yaml.",
        "nl": "{n} assets worden getest, elk met zijn eigen carry_assets.yaml-instellingen.",
        "zh": "将测试 {n} 个资产，每个使用其自身的 carry_assets.yaml 设置。",
    },
    "backtest_per_asset_note": {
        "fr": "Capital et fraction lus par actif depuis carry_assets.yaml.",
        "en": "Capital and fraction are read per asset from carry_assets.yaml.",
        "de": "Kapital und Fraktion werden pro Asset aus carry_assets.yaml gelesen.",
        "es": "El capital y la fracción se leen por activo desde carry_assets.yaml.",
        "it": "Capitale e frazione sono letti per asset da carry_assets.yaml.",
        "pt": "O capital e a fração são lidos por ativo a partir de carry_assets.yaml.",
        "nl": "Kapitaal en fractie worden per asset uit carry_assets.yaml gelezen.",
        "zh": "每个资产的资金与比例均从 carry_assets.yaml 读取。",
    },
    "no_trades_recorded": {
        "fr": "Aucun trade enregistré.", "en": "No trades recorded.",
        "de": "Keine Trades aufgezeichnet.", "es": "No hay operaciones registradas.",
        "it": "Nessuna operazione registrata.", "pt": "Nenhuma operação registrada.",
        "nl": "Geen trades geregistreerd.", "zh": "暂无交易记录。",
    },

    # ── Reflections tab ─────────────────────────────────────────────────────

    # ── Decisions tab ───────────────────────────────────────────────────────
    "decisions_count": {
        "fr": "{n} décision(s) trouvée(s)",
        "en": "{n} decision(s) found",
        "de": "{n} Entscheidung(en) gefunden",
        "es": "{n} decisión(es) encontrada(s)",
        "it": "{n} decisione/i trovata/e",
        "pt": "{n} decisão(ões) encontrada(s)",
        "nl": "{n} beslissing(en) gevonden",
        "zh": "找到 {n} 条决策",
    },
    "decisions_empty": {
        "fr": "Aucune décision enregistrée. Les décisions apparaîtront après le premier cycle DAG.",
        "en": "No decisions recorded. Decisions will appear after the first DAG cycle.",
        "de": "Keine Entscheidungen aufgezeichnet. Entscheidungen erscheinen nach dem ersten DAG-Zyklus.",
        "es": "No hay decisiones registradas. Las decisiones aparecerán después del primer ciclo DAG.",
        "it": "Nessuna decisione registrata. Le decisioni appariranno dopo il primo ciclo DAG.",
        "pt": "Nenhuma decisão registrada. As decisões aparecerão após o primeiro ciclo DAG.",
        "nl": "Geen beslissingen geregistreerd. Beslissingen verschijnen na de eerste DAG-cyclus.",
        "zh": "暂无决策记录。决策将在第一个DAG周期后出现。",
    },

    # ── DAG status (Next.js frontend) ───────────────────────────────────────

    # ── UI status messages ────────────────────────────────────────────────
    "formula_data_unavailable": {
        "fr": "Données de formule non disponibles pour ce trade.",
        "en": "Formula data not available for this trade.",
        "de": "Formeldaten für diesen Trade nicht verfügbar.",
        "es": "Datos de fórmula no disponibles para esta operación.",
        "it": "Dati formula non disponibili per questa operazione.",
        "pt": "Dados de fórmula não disponíveis para esta operação.",
        "nl": "Formulegegevens niet beschikbaar voor deze trade.",
        "zh": "该交易无公式数据。",
    },
    "agent_summary_unavailable": {
        "fr": "Pas de résumé disponible pour cet agent.",
        "en": "No summary available for this agent.",
        "de": "Keine Zusammenfassung für diesen Agenten verfügbar.",
        "es": "No hay resumen disponible para este agente.",
        "it": "Nessun riepilogo disponibile per questo agente.",
        "pt": "Nenhum resumo disponível para este agente.",
        "nl": "Geen samenvatting beschikbaar voor deze agent.",
        "zh": "该代理无可用摘要。",
    },
    "agent_scores_unavailable": {
        "fr": "Scores agents non disponibles.",
        "en": "Agent scores not available.",
        "de": "Agenten-Scores nicht verfügbar.",
        "es": "Puntuaciones de agentes no disponibles.",
        "it": "Punteggi agenti non disponibili.",
        "pt": "Pontuações dos agentes não disponíveis.",
        "nl": "Agentscores niet beschikbaar.",
        "zh": "代理评分不可用。",
    },
    "market_indicators_unavailable": {
        "fr": "Indicateurs de marché non disponibles.",
        "en": "Market indicators not available.",
        "de": "Marktindikatoren nicht verfügbar.",
        "es": "Indicadores de mercado no disponibles.",
        "it": "Indicatori di mercato non disponibili.",
        "pt": "Indicadores de mercado não disponíveis.",
        "nl": "Marktindicatoren niet beschikbaar.",
        "zh": "市场指标不可用。",
    },
    "blocked_prefix": {
        "fr": "Bloqué : ", "en": "Blocked: ", "de": "Blockiert: ",
        "es": "Bloqueado: ", "it": "Bloccato: ", "pt": "Bloqueado: ",
        "nl": "Geblokkeerd: ", "zh": "已阻止：",
    },
    "ai_explanation_unavailable": {
        "fr": "Pas d'explication IA pour ce trade.",
        "en": "No AI explanation for this trade.",
        "de": "Keine KI-Erklärung für diesen Trade.",
        "es": "Sin explicación de IA para esta operación.",
        "it": "Nessuna spiegazione IA per questa operazione.",
        "pt": "Sem explicação de IA para esta operação.",
        "nl": "Geen AI-uitleg voor deze trade.",
        "zh": "该交易无 AI 解释。",
    },
    "asset_config_module_unavailable": {
        "fr": "Module asset_config indisponible. Déployez la dernière version.",
        "en": "asset_config module not available. Please deploy the latest version.",
        "de": "Modul asset_config nicht verfügbar. Bitte die neueste Version bereitstellen.",
        "es": "Módulo asset_config no disponible. Despliegue la última versión.",
        "it": "Modulo asset_config non disponibile. Distribuire l'ultima versione.",
        "pt": "Módulo asset_config não disponível. Implante a versão mais recente.",
        "nl": "Module asset_config niet beschikbaar. Deploy de nieuwste versie.",
        "zh": "asset_config 模块不可用。请部署最新版本。",
    },
    "backtest_carry_caption": {
        "fr": "Backtest de la collecte de funding · Short Perp + Long Spot · Market-neutral",
        "en": "Funding collection backtest · Short Perp + Long Spot · Market-neutral",
        "de": "Backtest der Funding-Erhebung · Short Perp + Long Spot · Marktneutral",
        "es": "Backtest de recolección de funding · Short Perp + Long Spot · Market-neutral",
        "it": "Backtest della raccolta funding · Short Perp + Long Spot · Market-neutral",
        "pt": "Backtest da coleta de funding · Short Perp + Long Spot · Market-neutral",
        "nl": "Backtest van fundinginning · Short Perp + Long Spot · Marktneutraal",
        "zh": "资金费收取回测 · 永续空头 + 现货多头 · 市场中性",
    },
    "logs_memory_caption": {
        "fr": "Les logs sont en mémoire (buffer 200 lignes). Ils se renouvellent automatiquement.",
        "en": "Logs are held in memory (200-line buffer). They refresh automatically.",
        "de": "Logs werden im Speicher gehalten (200-Zeilen-Puffer). Sie aktualisieren sich automatisch.",
        "es": "Los logs están en memoria (búfer de 200 líneas). Se renuevan automáticamente.",
        "it": "I log sono in memoria (buffer 200 righe). Si aggiornano automaticamente.",
        "pt": "Os logs ficam em memória (buffer de 200 linhas). Renovam-se automaticamente.",
        "nl": "Logs staan in het geheugen (buffer van 200 regels). Ze vernieuwen automatisch.",
        "zh": "日志保存在内存中（200 行缓冲），会自动刷新。",
    },
    "reset_warning_trades": {
        "fr": "Cela supprimera tout l'historique des trades et les positions ouvertes. Le cycle carry continuera normalement.",
        "en": "This will delete all trade history and open positions. The carry cycle will continue normally.",
        "de": "Dies löscht die gesamte Handelshistorie und offene Positionen. Der Carry-Zyklus läuft normal weiter.",
        "es": "Esto eliminará todo el historial de operaciones y las posiciones abiertas. El ciclo carry continuará normalmente.",
        "it": "Questo eliminerà tutto lo storico operazioni e le posizioni aperte. Il ciclo carry continuerà normalmente.",
        "pt": "Isto eliminará todo o histórico de operações e as posições abertas. O ciclo carry continuará normalmente.",
        "nl": "Dit verwijdert de volledige handelsgeschiedenis en open posities. De carry-cyclus loopt normaal door.",
        "zh": "这将删除所有交易历史和未平仓持仓。carry 周期将照常运行。",
    },
    "reset_caption_trades": {
        "fr": "Supprime tous les trades de la base et vide le cache du dashboard.",
        "en": "Deletes all trades from the database and clears the dashboard cache.",
        "de": "Löscht alle Trades aus der Datenbank und leert den Dashboard-Cache.",
        "es": "Elimina todas las operaciones de la base de datos y vacía la caché del dashboard.",
        "it": "Elimina tutte le operazioni dal database e svuota la cache della dashboard.",
        "pt": "Elimina todas as operações da base de dados e limpa a cache do dashboard.",
        "nl": "Verwijdert alle trades uit de database en leegt de dashboardcache.",
        "zh": "从数据库删除所有交易并清空仪表板缓存。",
    },
    "decisions_caption_cycle": {
        "fr": "Chaque décision du cycle carry (8h) — filtrable par actif.",
        "en": "Every carry cycle decision (8h) — filterable by asset.",
        "de": "Jede Entscheidung des Carry-Zyklus (8h) — nach Asset filterbar.",
        "es": "Cada decisión del ciclo carry (8h) — filtrable por activo.",
        "it": "Ogni decisione del ciclo carry (8h) — filtrabile per asset.",
        "pt": "Cada decisão do ciclo carry (8h) — filtrável por ativo.",
        "nl": "Elke beslissing van de carry-cyclus (8u) — filterbaar per asset.",
        "zh": "carry 周期的每次决策（8 小时）——可按资产筛选。",
    },
    "paper_trading_mode": {
        "fr": "Mode : paper trading", "en": "Mode: paper trading",
        "de": "Modus: Paper Trading", "es": "Modo: paper trading",
        "it": "Modalità: paper trading", "pt": "Modo: paper trading",
        "nl": "Modus: paper trading", "zh": "模式：模拟交易",
    },
    "no_open_carry_positions": {
        "fr": "Aucune position carry ouverte — funding trop bas sur le marché actuel",
        "en": "No open carry positions — funding rates too low in current market",
        "de": "Keine offenen Carry-Positionen — Funding-Raten im aktuellen Markt zu niedrig",
        "es": "Sin posiciones carry abiertas — funding demasiado bajo en el mercado actual",
        "it": "Nessuna posizione carry aperta — funding troppo basso nel mercato attuale",
        "pt": "Sem posições carry abertas — funding demasiado baixo no mercado atual",
        "nl": "Geen open carry-posities — funding te laag in de huidige markt",
        "zh": "没有未平仓的 carry 持仓——当前市场资金费率过低",
    },
    "no_decisions_yet": {
        "fr": "Aucune décision pour l'instant — premier cycle en attente",
        "en": "No decisions yet — first cycle pending",
        "de": "Noch keine Entscheidungen — erster Zyklus ausstehend",
        "es": "Aún no hay decisiones — primer ciclo pendiente",
        "it": "Nessuna decisione ancora — primo ciclo in attesa",
        "pt": "Ainda sem decisões — primeiro ciclo pendente",
        "nl": "Nog geen beslissingen — eerste cyclus in afwachting",
        "zh": "暂无决策——首个周期待运行",
    },

    # ── Rechargement de la config (bouton Carry Assets) ───────────────────
    "carry_apply_reload_btn": {
        "fr": "🚀 Appliquer & recharger",
        "en": "🚀 Apply & reload",
        "de": "🚀 Anwenden & neu laden",
        "es": "🚀 Aplicar y recargar",
        "it": "🚀 Applica e ricarica",
        "pt": "🚀 Aplicar e recarregar",
        "nl": "🚀 Toepassen & herladen",
        "zh": "🚀 应用并重载",
    },
    "carry_apply_reload_help": {
        "fr": "Applique carry_assets.yaml au process API et démarre les tickers des actifs ajoutés. Sans cet appel, les changements n'étaient pris en compte qu'après redémarrage du container.",
        "en": "Applies carry_assets.yaml to the API process and starts price tickers for newly added assets. Without this call, changes only took effect after a container restart.",
        "de": "Wendet carry_assets.yaml auf den API-Prozess an und startet Preisticker für neue Assets. Ohne diesen Aufruf wirkten Änderungen erst nach einem Container-Neustart.",
        "es": "Aplica carry_assets.yaml al proceso API e inicia los tickers de precio de los activos añadidos. Sin esta llamada, los cambios solo surtían efecto tras reiniciar el contenedor.",
        "it": "Applica carry_assets.yaml al processo API e avvia i ticker dei prezzi per i nuovi asset. Senza questa chiamata, le modifiche avevano effetto solo dopo il riavvio del container.",
        "pt": "Aplica carry_assets.yaml ao processo da API e inicia os tickers de preço dos novos ativos. Sem esta chamada, as alterações só tinham efeito após reiniciar o contentor.",
        "nl": "Past carry_assets.yaml toe op het API-proces en start prijstikkers voor nieuw toegevoegde assets. Zonder deze aanroep gingen wijzigingen pas in na een containerherstart.",
        "zh": "将 carry_assets.yaml 应用到 API 进程，并为新增资产启动价格行情。若不调用，修改仅在容器重启后生效。",
    },
    "carry_reload_ok": {
        "fr": "✅ Config appliquée à l'API — {n} actifs actifs : {assets}",
        "en": "✅ Config applied to the API — {n} active assets: {assets}",
        "de": "✅ Konfiguration auf die API angewendet — {n} aktive Assets: {assets}",
        "es": "✅ Configuración aplicada a la API — {n} activos activos: {assets}",
        "it": "✅ Configurazione applicata all'API — {n} asset attivi: {assets}",
        "pt": "✅ Configuração aplicada à API — {n} ativos ativos: {assets}",
        "nl": "✅ Config toegepast op de API — {n} actieve assets: {assets}",
        "zh": "✅ 配置已应用到 API — {n} 个活跃资产：{assets}",
    },
    "carry_reload_warn": {
        "fr": "⚠️ Avertissements : {errors}",
        "en": "⚠️ Warnings: {errors}",
        "de": "⚠️ Warnungen: {errors}",
        "es": "⚠️ Advertencias: {errors}",
        "it": "⚠️ Avvisi: {errors}",
        "pt": "⚠️ Avisos: {errors}",
        "nl": "⚠️ Waarschuwingen: {errors}",
        "zh": "⚠️ 警告：{errors}",
    },
    "carry_reload_error": {
        "fr": "Échec du rechargement — {err}",
        "en": "Reload failed — {err}",
        "de": "Neuladen fehlgeschlagen — {err}",
        "es": "Error al recargar — {err}",
        "it": "Ricaricamento non riuscito — {err}",
        "pt": "Falha ao recarregar — {err}",
        "nl": "Herladen mislukt — {err}",
        "zh": "重载失败 — {err}",
    },
    "filter_all": {
        "fr": "Tous", "en": "All", "de": "Alle", "es": "Todos",
        "it": "Tutti", "pt": "Todos", "nl": "Alle", "zh": "全部",
    },
    "carry_staking_annual": {
        "fr": "Staking annuel (%)", "en": "Annual staking (%)",
        "de": "Jährliches Staking (%)", "es": "Staking anual (%)",
        "it": "Staking annuale (%)", "pt": "Staking anual (%)",
        "nl": "Jaarlijkse staking (%)", "zh": "年化质押收益 (%)",
    },
    "carry_staking_annual_help": {
        "fr": "Rendement annualisé simulé sur le capital inactif (position fermée). Appliqué par période de 8h.",
        "en": "Simulated annualized yield on idle capital (position closed). Accrued per 8h period.",
        "de": "Simulierte annualisierte Rendite auf inaktives Kapital (Position geschlossen). Pro 8-Stunden-Periode gutgeschrieben.",
        "es": "Rendimiento anualizado simulado sobre el capital inactivo (posición cerrada). Se acumula por periodo de 8h.",
        "it": "Rendimento annualizzato simulato sul capitale inattivo (posizione chiusa). Maturato per periodo di 8h.",
        "pt": "Rendimento anualizado simulado sobre o capital inativo (posição fechada). Acumulado por período de 8h.",
        "nl": "Gesimuleerd jaarlijks rendement op inactief kapitaal (positie gesloten). Toegerekend per periode van 8 uur.",
        "zh": "对闲置资金（无持仓时）模拟的年化收益，按每 8 小时计入。",
    },

    # ── Backtest ──────────────────────────────────────────────────────────
    "backtest_capital": {
        "fr": "Capital ($)", "en": "Capital ($)", "de": "Kapital ($)",
        "es": "Capital ($)", "it": "Capitale ($)", "pt": "Capital ($)",
        "nl": "Kapitaal ($)", "zh": "资金 ($)",
    },
    "backtest_capital_help": {
        "fr": "Capital alloué à cet actif pour le backtest. Défaut : valeur de carry_assets.yaml.",
        "en": "Capital allocated to this asset for the backtest. Default: value from carry_assets.yaml.",
        "de": "Für dieses Asset im Backtest alloziertes Kapital. Standard: Wert aus carry_assets.yaml.",
        "es": "Capital asignado a este activo para el backtest. Por defecto: valor de carry_assets.yaml.",
        "it": "Capitale assegnato a questo asset per il backtest. Predefinito: valore da carry_assets.yaml.",
        "pt": "Capital atribuído a este ativo para o backtest. Predefinição: valor de carry_assets.yaml.",
        "nl": "Kapitaal toegewezen aan dit asset voor de backtest. Standaard: waarde uit carry_assets.yaml.",
        "zh": "分配给该资产用于回测的资金。默认：carry_assets.yaml 中的值。",
    },
    "backtest_fraction": {
        "fr": "Fraction du capital en carry", "en": "Fraction of capital in carry",
        "de": "Kapitalanteil im Carry", "es": "Fracción del capital en carry",
        "it": "Frazione di capitale in carry", "pt": "Fração do capital em carry",
        "nl": "Deel van kapitaal in carry", "zh": "投入 carry 的资金比例",
    },
    "backtest_fraction_help": {
        "fr": "Part du capital immobilisée dans la position carry (défaut : valeur de carry_assets.yaml).",
        "en": "Share of capital committed to the carry position (default: value from carry_assets.yaml).",
        "de": "Anteil des in der Carry-Position gebundenen Kapitals (Standard: Wert aus carry_assets.yaml).",
        "es": "Parte del capital comprometida en la posición carry (por defecto: valor de carry_assets.yaml).",
        "it": "Quota di capitale impegnata nella posizione carry (predefinito: valore da carry_assets.yaml).",
        "pt": "Parte do capital comprometida na posição carry (predefinição: valor de carry_assets.yaml).",
        "nl": "Deel van het kapitaal vastgelegd in de carry-positie (standaard: waarde uit carry_assets.yaml).",
        "zh": "投入 carry 持仓的资金占比（默认：carry_assets.yaml 中的值）。",
    },
    "backtest_running": {
        "fr": "Backtest Funding Carry — {symbol} sur {days}j…",
        "en": "Funding Carry backtest — {symbol} over {days}d…",
        "de": "Funding-Carry-Backtest — {symbol} über {days} Tage…",
        "es": "Backtest Funding Carry — {symbol} en {days}d…",
        "it": "Backtest Funding Carry — {symbol} su {days}g…",
        "pt": "Backtest Funding Carry — {symbol} em {days}d…",
        "nl": "Funding Carry-backtest — {symbol} over {days} dagen…",
        "zh": "资金费 carry 回测 — {symbol}，{days} 天…",
    },

    # -- Misc controls --
    "carry_apply_optimized_btn": {
        "fr": "📊 Appliquer optimisés", "en": "📊 Apply optimized",
        "de": "📊 Optimierte anwenden", "es": "📊 Aplicar optimizados",
        "it": "📊 Applica ottimizzati", "pt": "📊 Aplicar otimizados",
        "nl": "📊 Geoptimaliseerd toepassen", "zh": "📊 应用优化参数",
    },
    "carry_apply_optimized_help": {
        "fr": "Copie les paramètres _optimized_* vers les paramètres réels (actifs non verrouillés).",
        "en": "Copies the _optimized_* parameters to the live ones (unlocked assets only).",
        "de": "Kopiert die _optimized_*-Parameter in die aktiven Parameter (nur ungesperrte Assets).",
        "es": "Copia los parámetros _optimized_* a los reales (solo activos no bloqueados).",
        "it": "Copia i parametri _optimized_* su quelli reali (solo asset non bloccati).",
        "pt": "Copia os parâmetros _optimized_* para os reais (apenas ativos não bloqueados).",
        "nl": "Kopieert de _optimized_*-parameters naar de actieve (alleen niet-vergrendelde assets).",
        "zh": "将 _optimized_* 参数复制到实际参数（仅限未锁定的资产）。",
    },
    "clear_btn": {
        "fr": "🗑️ Vider", "en": "🗑️ Clear", "de": "🗑️ Leeren",
        "es": "🗑️ Vaciar", "it": "🗑️ Svuota", "pt": "🗑️ Limpar",
        "nl": "🗑️ Wissen", "zh": "🗑️ 清空",
    },
    "clear_btn_help": {
        "fr": "Efface les logs en mémoire (buffer circulaire automatique).",
        "en": "Clears the in-memory logs (automatic circular buffer).",
        "de": "Löscht die Logs im Speicher (automatischer Ringpuffer).",
        "es": "Borra los logs en memoria (búfer circular automático).",
        "it": "Cancella i log in memoria (buffer circolare automatico).",
        "pt": "Limpa os logs em memória (buffer circular automático).",
        "nl": "Wist de logs in het geheugen (automatische ringbuffer).",
        "zh": "清除内存中的日志（自动循环缓冲）。",
    },
    "export_csv_btn": {
        "fr": "⬇️ Exporter CSV", "en": "⬇️ Export CSV", "de": "⬇️ CSV exportieren",
        "es": "⬇️ Exportar CSV", "it": "⬇️ Esporta CSV", "pt": "⬇️ Exportar CSV",
        "nl": "⬇️ CSV exporteren", "zh": "⬇️ 导出 CSV",
    },
    "col_number": {
        "fr": "Nombre", "en": "Count", "de": "Anzahl", "es": "Cantidad",
        "it": "Quantità", "pt": "Quantidade", "nl": "Aantal", "zh": "数量",
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
    # Explicit fallback: EN -> FR -> key
    return entry.get("en") or entry.get("fr") or key
