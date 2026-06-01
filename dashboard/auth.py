"""
dashboard/auth.py — Authentification username + mot de passe (bcrypt) + TOTP 2FA.

Rôles :
  "back"  → accès back-office (admin) — TOTP 2FA obligatoire à la première connexion.
  "front" → accès front uniquement — pas de 2FA.
  guest_mode (settings) → accès front sans connexion.

Session : session_state Streamlit + _sid param URL → SQLite store.
Passwords : bcrypt (rounds=12).
2FA     : TOTP RFC 6238 (pyotp) — Google Authenticator, Authy, Bitwarden, 1Password.
Users   : config/users.yaml — géré automatiquement.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

import streamlit as st
import yaml
from utils.i18n import t

logger = logging.getLogger("zeitgeist.auth")

_USERS_FILE = Path(__file__).parent.parent / "config" / "users.yaml"

# ─────────────────────────────────────────────────────────────────────────────
# Store de sessions SQLite (survit aux redémarrages Streamlit et aux multi-workers)
# ─────────────────────────────────────────────────────────────────────────────
_SESSION_DB = Path(__file__).parent.parent / "storage" / "atlas_sessions.db"
_SESSION_LOCK = threading.Lock()


def _init_session_db() -> None:
    """Crée la table sessions si absente."""
    _SESSION_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(_SESSION_DB)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                username   TEXT NOT NULL,
                roles      TEXT NOT NULL,
                exp        REAL NOT NULL
            )
        """)


def _store_session(username: str, roles: list[str], expiry_days: int) -> str:
    """Crée une session SQLite, retourne le session_id (UUID)."""
    session_id = str(uuid.uuid4())
    exp = time.time() + expiry_days * 86400
    _init_session_db()
    with _SESSION_LOCK:
        with sqlite3.connect(str(_SESSION_DB)) as conn:
            conn.execute("DELETE FROM sessions WHERE exp < ?", (time.time(),))
            conn.execute(
                "INSERT OR REPLACE INTO sessions (session_id, username, roles, exp) VALUES (?,?,?,?)",
                (session_id, username, json.dumps(roles), exp),
            )
    return session_id


def _get_stored_session(session_id: str) -> dict | None:
    """Récupère une session SQLite. None si expirée/invalide."""
    if not session_id:
        return None
    try:
        _init_session_db()
        with sqlite3.connect(str(_SESSION_DB)) as conn:
            row = conn.execute(
                "SELECT username, roles, exp FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row and row[2] > time.time():
                return {"username": row[0], "roles": json.loads(row[1])}
    except Exception as exc:
        logger.debug(f"Session lookup failed: {exc}")
    return None


def _delete_session(session_id: str) -> None:
    """Supprime une session SQLite."""
    if not session_id:
        return
    try:
        _init_session_db()
        with sqlite3.connect(str(_SESSION_DB)) as conn:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Persistence utilisateurs (config/users.yaml)
# ─────────────────────────────────────────────────────────────────────────────

def load_users_config() -> dict:
    """Charge la configuration utilisateurs. Retourne un dict vide si absent."""
    if _USERS_FILE.exists():
        with open(_USERS_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {"users": {}, "settings": {}}
    return {"users": {}, "settings": {}}


def save_users_config(data: dict) -> None:
    _USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_USERS_FILE, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


# ─────────────────────────────────────────────────────────────────────────────
# Mots de passe (bcrypt)
# ─────────────────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    import bcrypt
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(12)).decode()


def _verify_password(password: str, hashed: str) -> bool:
    try:
        import bcrypt
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Session
# ─────────────────────────────────────────────────────────────────────────────

def get_session(cm=None) -> dict | None:
    """
    Retourne {username, roles} si session valide, None sinon.
    Ordre de vérification :
      1. session_state (rerun interne — le plus rapide)
      2. _sid dans query params → store serveur SQLite (persiste après F5)
    Note: extra_streamlit_components CookieManager supprimé — incompatible
    avec Streamlit ≥1.35 (cause des reruns intempestifs bloquant le login).
    """
    # 1. session_state
    if st.session_state.get("_auth_session"):
        return st.session_state["_auth_session"]

    # 2. _sid dans l'URL → session SQLite (survit au rechargement de page)
    try:
        sid = st.query_params.get("_sid", "")
        if sid:
            stored = _get_stored_session(sid)
            if stored:
                st.session_state["_auth_session"] = stored
                st.session_state["_session_id"] = sid
                return stored
    except Exception:
        pass
    return None


def has_role(session: dict | None, role: str) -> bool:
    return bool(session and role in session.get("roles", []))


def logout(cm=None) -> None:
    sid = st.session_state.get("_session_id", "")
    _delete_session(sid)
    for k in ("_auth_session", "_auth_step", "_auth_pending_user",
              "_auth_totp_new_secret", "_session_id", "admin_authenticated",
              "_suppress_auth_ui", "_totp_login_ready"):
        st.session_state.pop(k, None)
    try:
        st.query_params.pop("_sid", None)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# UI d'authentification
# ─────────────────────────────────────────────────────────────────────────────

def render_auth(cm=None) -> None:
    """
    Affiche le formulaire d'authentification adapté à l'étape courante.
    Gère : premier lancement, login, TOTP setup, TOTP verify.
    Cookie manager supprimé (incompatible Streamlit ≥1.35) — session via _sid URL.
    """
    # Kill-switch global: si active, ne jamais rendre de blocs d'auth.
    if st.session_state.get("_suppress_auth_ui", False):
        return

    cfg = load_users_config()
    users: dict = cfg.get("users", {})
    settings: dict = cfg.get("settings", {})
    expiry_days = int(settings.get("cookie_expiry_days", 7))

    # Garde-fou: si l'utilisateur est deja authentifie, ne jamais afficher
    # les formulaires d'auth/login/2FA meme si render_auth() est appelee.
    current = get_session()
    if current and (has_role(current, "back") or has_role(current, "front")):
        st.session_state.pop("_auth_step", None)
        st.session_state.pop("_auth_pending_user", None)
        st.session_state.pop("_auth_totp_new_secret", None)
        return

    # 1. Premier lancement : aucun compte
    has_users = any(u.get("password_hash") for u in users.values())
    if not has_users:
        _render_first_setup(cfg)
        return

    step = st.session_state.get("_auth_step", "login")
    pending_user = st.session_state.get("_auth_pending_user", "")

    if step == "totp_setup" and pending_user:
        _render_totp_setup(pending_user, cfg, expiry_days)
        return

    if step == "totp_verify" and pending_user:
        _render_totp_verify(pending_user, cfg, expiry_days)
        return

    # S5: Rate limiting — max 5 tentatives en 5 min
    _now = time.time()
    _lockout_until = st.session_state.get("_login_lockout_until", 0.0)
    if _now < _lockout_until:
        _remaining = int(_lockout_until - _now)
        _centered_open()
        st.error(t("login_locked").format(s=_remaining))
        _centered_close()
        return

    # 2. Formulaire login
    _centered_open()
    st.markdown("### 🔐 Atlas Trader")

    with st.form("atlas_login", clear_on_submit=False):
        username = st.text_input(t("login_username"))
        password = st.text_input(t("login_password"), type="password")
        submitted = st.form_submit_button(t("login_btn"), use_container_width=True, type="primary")

    if submitted:
        user = users.get(username)
        if not user or not _verify_password(password, user.get("password_hash", "")):
            _fails = st.session_state.get("_login_fails", 0) + 1
            st.session_state["_login_fails"] = _fails
            if _fails >= 5:
                st.session_state["_login_lockout_until"] = time.time() + 300
                st.session_state["_login_fails"] = 0
            st.error(t("login_wrong"))
            _centered_close()
            return

        # Connexion réussie — réinitialise les compteurs
        st.session_state.pop("_login_fails", None)
        st.session_state.pop("_login_lockout_until", None)

        roles = user.get("roles", [])
        st.session_state["_auth_pending_user"] = username

        # Admin → TOTP obligatoire
        if "back" in roles and user.get("totp_enabled", True):
            st.session_state["_auth_step"] = (
                "totp_setup" if not user.get("totp_secret") else "totp_verify"
            )
            # Vider le slot parent (titre + info + formulaire login) avant le rerun
            # pour éviter que le formulaire login apparaisse à côté du formulaire TOTP.
            _outer = st.session_state.get("_auth_slot")
            if _outer is not None:
                try:
                    _outer.empty()
                except Exception:
                    pass
            st.rerun()
            return

        # Utilisateur front-only → connexion directe sans 2FA
        _centered_close()
        _finalize_login(username, roles, expiry_days)

    _centered_close()


def _render_first_setup(cfg: dict) -> None:
    """Formulaire de création du compte admin lors du premier lancement."""
    _centered_open()
    st.markdown("### ⚙️ Configuration initiale — Atlas Trader")
    st.info(t("setup_info"))
    with st.form("first_setup"):
        username = st.text_input(t("setup_username"), value="admin")
        pwd1 = st.text_input(t("setup_pwd_hint"), type="password")
        pwd2 = st.text_input(t("setup_confirm_pwd"), type="password")
        submitted = st.form_submit_button(t("setup_create_btn"), type="primary", use_container_width=True)

    if submitted:
        if len(pwd1) < 8:
            st.error(t("setup_pwd_min_err"))
        elif pwd1 != pwd2:
            st.error(t("usr_pwd_mismatch"))
        else:
            cfg.setdefault("users", {})[username] = {
                "password_hash": hash_password(pwd1),
                "roles": ["front", "back"],
                "totp_enabled": True,
                "totp_secret": "",
            }
            cfg.setdefault("settings", {}).setdefault("guest_mode", True)
            cfg["settings"].setdefault("cookie_expiry_days", 7)
            save_users_config(cfg)
            st.success(t("setup_success").format(uname=username))
            _outer = st.session_state.get("_auth_slot")
            if _outer is not None:
                try:
                    _outer.empty()
                except Exception:
                    pass
            st.rerun()

    _centered_close()


def _render_totp_setup(username: str, cfg: dict, expiry_days: int) -> None:
    """Configuration TOTP initiale : génère et affiche le QR code."""
    active = get_session()
    if active and has_role(active, "back"):
        st.session_state.pop("_auth_step", None)
        st.session_state.pop("_auth_pending_user", None)
        st.session_state.pop("_auth_totp_new_secret", None)
        return

    if st.session_state.get("_suppress_auth_ui", False) or st.session_state.get("admin_authenticated", False):
        st.session_state.pop("_auth_step", None)
        st.session_state.pop("_auth_pending_user", None)
        st.session_state.pop("_auth_totp_new_secret", None)
        return

    import io
    import pyotp
    import qrcode

    if "_auth_totp_new_secret" not in st.session_state:
        st.session_state["_auth_totp_new_secret"] = pyotp.random_base32()
    secret = st.session_state["_auth_totp_new_secret"]

    uri = pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name="Atlas Trader")
    qr = qrcode.QRCode(box_size=5, border=2)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    _setup_slot = st.empty()
    with _setup_slot.container():
        st.markdown("### 📱 Configuration 2FA — Google Authenticator")
        st.info(t("totp_setup_info"))
        col_qr, col_info = st.columns([1, 1])
        with col_qr:
            st.image(buf, width=190)
        with col_info:
            st.markdown(t("totp_manual_key"))
            st.code(secret, language=None)
            st.caption(t("totp_compat"))

        with st.form("totp_setup_form"):
            code = st.text_input(t("totp_code_input"), max_chars=6, placeholder="123456")
            submitted = st.form_submit_button(t("totp_confirm_btn"), type="primary", use_container_width=True)

    if submitted:
        if pyotp.TOTP(secret).verify(code, valid_window=1):
            users = cfg.get("users", {})
            users[username]["totp_secret"] = secret
            users[username]["totp_enabled"] = True
            save_users_config(cfg)
            st.session_state.pop("_auth_totp_new_secret", None)
            st.session_state.pop("_auth_step", None)
            roles = users[username].get("roles", [])
            _setup_slot.empty()  # efface le formulaire AVANT le rerun → zéro bloc fantôme
            # Effacer aussi le slot parent (titre + info)
            _outer = st.session_state.pop("_auth_slot", None)
            if _outer is not None:
                try:
                    _outer.empty()
                except Exception:
                    pass
            _finalize_login(username, roles, expiry_days)
            return
        else:
            st.error(t("totp_wrong"))


def _render_totp_verify(username: str, cfg: dict, expiry_days: int) -> None:
    """Vérification TOTP lors d'une connexion normale."""
    active = get_session()
    if active and has_role(active, "back"):
        st.session_state.pop("_auth_step", None)
        st.session_state.pop("_auth_pending_user", None)
        st.session_state.pop("_auth_totp_new_secret", None)
        return

    if st.session_state.get("_suppress_auth_ui", False) or st.session_state.get("admin_authenticated", False):
        st.session_state.pop("_auth_step", None)
        st.session_state.pop("_auth_pending_user", None)
        st.session_state.pop("_auth_totp_new_secret", None)
        return

    import pyotp

    users = cfg.get("users", {})

    # st.empty() : tout le formulaire TOTP est rendu dans ce slot.
    # Sur validation réussie → _totp_slot.empty() efface le slot AVANT st.rerun().
    # Le prochain run démarre avec un DOM vierge → zéro bloc fantôme.
    _totp_slot = st.empty()
    with _totp_slot.container():
        st.markdown(f"### 🔐 {t('totp_verify_title')}")
        st.caption(t("totp_account").format(username=username))

        with st.form("totp_verify_form"):
            code = st.text_input(
                t("totp_code_input"),
                max_chars=6,
                placeholder="123456",
                autocomplete="one-time-code",
            )
            col_a, col_b = st.columns([3, 1])
            with col_a:
                submitted = st.form_submit_button(t("totp_verify_btn"), type="primary", use_container_width=True)
            with col_b:
                back = st.form_submit_button(t("totp_back_btn"), use_container_width=True)

    if back:
        _totp_slot.empty()
        # Effacer aussi le slot parent (titre + info + formulaire)
        _outer = st.session_state.pop("_auth_slot", None)
        if _outer is not None:
            try:
                _outer.empty()
            except Exception:
                pass
        st.session_state.pop("_auth_step", None)
        st.session_state.pop("_auth_pending_user", None)
        st.rerun()

    if submitted:
        user = users.get(username, {})
        if pyotp.TOTP(user["totp_secret"]).verify(code, valid_window=1):
            st.session_state.pop("_auth_step", None)
            roles = user.get("roles", [])
            # Effacer le slot TOTP ET le slot parent atomiquement
            _totp_slot.empty()
            _outer = st.session_state.pop("_auth_slot", None)
            if _outer is not None:
                try:
                    _outer.empty()
                except Exception:
                    pass
            _finalize_login(username, roles, expiry_days)
            return
        else:
            st.error(t("totp_verify_wrong"))


def _finalize_login(username: str, roles: list[str], expiry_days: int = 7) -> None:
    """Finalise la connexion : crée la session SQLite + met à jour les query params + rerun."""
    session = {"username": username, "roles": roles}
    st.session_state["_auth_session"] = session
    st.session_state["admin_authenticated"] = "back" in roles
    st.session_state.pop("_auth_pending_user", None)
    st.session_state.pop("_auth_step", None)
    st.session_state.pop("_totp_login_ready", None)
    session_id = _store_session(username, roles, expiry_days)
    st.session_state["_session_id"] = session_id
    logger.info(f"Login: {username} roles={roles} sid={session_id[:8]}…")
    st.query_params["_sid"] = session_id
    st.query_params["admin"] = "1"
    st.rerun()


def _centered_open(width: int = 440) -> None:
    # Evite les wrappers HTML ouverts/fermés sur rerun qui peuvent laisser
    # des artefacts visuels dans Streamlit (bloc auth persistant).
    st.markdown("")


def _centered_close() -> None:
    # No-op: voir _centered_open.
    return


# ─────────────────────────────────────────────────────────────────────────────
# Gestion utilisateurs (onglet Admin)
# ─────────────────────────────────────────────────────────────────────────────

def render_users_admin() -> None:
    """Panneau de gestion des utilisateurs (onglet admin → Utilisateurs)."""
    import streamlit as st

    cfg = load_users_config()
    users: dict = cfg.get("users", {})
    settings: dict = cfg.get("settings", {})

    st.markdown(
        '<h4><i class="fas fa-users" style="margin-right:7px;color:#7986cb;"></i>'
        f"{t('usr_title')}</h4>",
        unsafe_allow_html=True,
    )

    # ── Paramètres globaux ──────────────────────────────────────────────────
    st.markdown(f"**{t('usr_session_settings')}**")
    col1, col2 = st.columns(2)
    with col1:
        settings["guest_mode"] = st.toggle(
            t("usr_guest_mode"),
            value=settings.get("guest_mode", True),
            help=t("usr_guest_help"),
        )
    with col2:
        settings["cookie_expiry_days"] = st.number_input(
            t("usr_session_days"),
            min_value=1,
            max_value=90,
            value=int(settings.get("cookie_expiry_days", 7)),
            help=t("usr_session_days_help"),
        )
    cfg["settings"] = settings
    st.markdown("---")

    # ── Liste des utilisateurs ───────────────────────────────────────────────
    st.markdown(f"**{t('usr_users_configured')}**")
    if not users:
        st.info(t("usr_no_users"))
    else:
        for uname, udata in list(users.items()):
            with st.expander(f"👤 {uname} — rôles : {', '.join(udata.get('roles', []))}"):
                roles = udata.get("roles", [])
                col_r1, col_r2 = st.columns(2)
                with col_r1:
                    has_front = st.toggle(t("usr_access_front"), value="front" in roles, key=f"front_{uname}")
                with col_r2:
                    has_back = st.toggle(
                        t("usr_access_back"),
                        value="back" in roles,
                        key=f"back_{uname}",
                    )
                new_roles = []
                if has_front:
                    new_roles.append("front")
                if has_back:
                    new_roles.append("back")
                udata["roles"] = new_roles

                # Reset mot de passe
                st.markdown(f"**{t('usr_change_pwd')}**")
                with st.form(f"reset_pwd_{uname}"):
                    new_pwd = st.text_input(t("usr_new_pwd"), type="password", key=f"npwd_{uname}")
                    if st.form_submit_button(t("usr_update_pwd"), key=f"btn_pwd_{uname}"):
                        if len(new_pwd) >= 8:
                            udata["password_hash"] = hash_password(new_pwd)
                            st.success(t("usr_pwd_updated"))
                        else:
                            st.error(t("usr_min_8"))

                # Reset TOTP
                if udata.get("totp_secret"):
                    if st.button(
                        t("usr_reset_2fa"),
                        key=f"reset_totp_{uname}",
                    ):
                        udata["totp_secret"] = ""
                        st.success(t("usr_reset_2fa_ok"))

                # Supprimer utilisateur
                if st.button(t("usr_delete_btn").format(uname=uname), key=f"del_{uname}", type="secondary"):
                    del cfg["users"][uname]
                    save_users_config(cfg)
                    st.success(t("usr_deleted_ok").format(uname=uname))
                    st.rerun()

                users[uname] = udata

    st.markdown("---")

    # ── Ajouter un utilisateur ───────────────────────────────────────────────
    st.markdown(f"**{t('usr_add_title')}**")
    with st.form("add_user"):
        col1, col2 = st.columns(2)
        with col1:
            new_username = st.text_input(t("usr_new_username"))
            new_pwd1 = st.text_input(t("usr_new_password"), type="password")
            new_pwd2 = st.text_input(t("usr_confirm_pwd"), type="password")
        with col2:
            role_front = st.toggle(t("usr_access_front"), value=True, key="new_front")
            role_back = st.toggle(t("usr_access_back_2fa"), value=False, key="new_back")
        submitted = st.form_submit_button(t("usr_add_btn"), type="primary")

    if submitted:
        if not new_username:
            st.error(t("usr_id_required"))
        elif new_username in users:
            st.error(t("usr_already_exists").format(uname=new_username))
        elif len(new_pwd1) < 8:
            st.error(t("usr_min_8"))
        elif new_pwd1 != new_pwd2:
            st.error(t("usr_pwd_mismatch"))
        else:
            new_roles = []
            if role_front:
                new_roles.append("front")
            if role_back:
                new_roles.append("back")
            cfg.setdefault("users", {})[new_username] = {
                "password_hash": hash_password(new_pwd1),
                "roles": new_roles,
                "totp_enabled": role_back,
                "totp_secret": "",
            }
            save_users_config(cfg)
            st.success(t("usr_created_ok").format(uname=new_username))
            st.rerun()

    # Sauvegarder les modifications (rôles, settings)
    st.markdown("---")
    if st.button(t("auth_save_changes"), type="primary", use_container_width=True):
        cfg["users"] = users
        save_users_config(cfg)
        st.success("✅ Configuration utilisateurs sauvegardée.")
