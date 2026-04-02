"""
dashboard/auth.py — Authentification multi-rôles avec TOTP (2FA) et cookie JWT.

Rôles :
  "back"  → accès back-office (admin) — TOTP 2FA obligatoire à la première connexion.
  "front" → accès front uniquement — pas de 2FA.
  guest_mode (settings) → accès front sans connexion.

Cookie  : JWT HS256 signé par AUTH_SECRET_KEY (env).
2FA     : TOTP RFC 6238 (pyotp) — Google Authenticator, Authy, Bitwarden, 1Password.
Passwords : bcrypt (rounds=12).
Users   : config/users.yaml — géré automatiquement.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st
import yaml

logger = logging.getLogger("zeitgeist.auth")

_USERS_FILE = Path(__file__).parent.parent / "config" / "users.yaml"
_COOKIE_NAME = "atlas_auth_v1"

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
# JWT + Cookie
# ─────────────────────────────────────────────────────────────────────────────

def _secret_key() -> str:
    key = os.getenv("AUTH_SECRET_KEY", "")
    if not key:
        # Dérivation depuis ADMIN_PASSWORD comme fallback sécurisé
        key = hashlib.sha256(
            os.getenv("ADMIN_PASSWORD", "atlas-no-secret-please-set-AUTH_SECRET_KEY").encode()
        ).hexdigest()
    return key


def _jwt_encode(username: str, roles: list[str], expiry_days: int) -> str:
    """Encode JWT HS256 — stdlib uniquement (pas besoin de PyJWT)."""
    import base64
    import hmac
    import json as _json
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()
    payload_data = {
        "sub": username,
        "roles": roles,
        "exp": int(time.time()) + expiry_days * 86400,
        "iat": int(time.time()),
    }
    payload = base64.urlsafe_b64encode(
        _json.dumps(payload_data, separators=(",", ":")).encode()
    ).rstrip(b"=").decode()
    signing_input = f"{header}.{payload}"
    sig = hmac.new(
        _secret_key().encode(), signing_input.encode(), "sha256"
    ).digest()
    signature = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    return f"{signing_input}.{signature}"


def _jwt_decode(token: str) -> dict | None:
    """Decode et vérifie un JWT HS256 — stdlib uniquement."""
    try:
        import base64
        import hmac
        import json as _json
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, payload_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}"
        expected_sig = hmac.new(
            _secret_key().encode(), signing_input.encode(), "sha256"
        ).digest()
        expected_b64 = base64.urlsafe_b64encode(expected_sig).rstrip(b"=").decode()
        if not hmac.compare_digest(sig_b64, expected_b64):
            return None
        # Décode le payload (padding base64 flexible)
        padding = 4 - len(payload_b64) % 4
        payload_bytes = base64.urlsafe_b64decode(payload_b64 + "=" * (padding % 4))
        return _json.loads(payload_bytes)
    except Exception:
        return None


def _write_cookie(cm, username: str, roles: list[str], expiry_days: int) -> None:
    try:
        token = _jwt_encode(username, roles, expiry_days)
        cm.set(
            _COOKIE_NAME,
            token,
            expires_at=datetime.now() + timedelta(days=expiry_days),
        )
    except Exception as exc:
        logger.debug(f"Cookie write skipped: {exc}")


def _delete_cookie(cm) -> None:
    try:
        cm.delete(_COOKIE_NAME)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Session
# ─────────────────────────────────────────────────────────────────────────────

def get_session(cm) -> dict | None:
    """
    Retourne {username, roles} si session valide, None sinon.
    Ordre de vérification :
      1. session_state (rerun interne — le plus rapide)
      2. _sid dans query params → store serveur (fiable sans timing)
      3. Cookie JWT (fallback pour accès direct sans _sid dans l'URL)
    """
    # 1. session_state
    if st.session_state.get("_auth_session"):
        return st.session_state["_auth_session"]

    # 2. Session ID dans l'URL (pas de dépendance composant React)
    sid = st.query_params.get("_sid", "")
    if sid:
        session = _get_stored_session(sid)
        if session:
            st.session_state["_auth_session"] = session
            st.session_state["_session_id"] = sid
            return session

    # 3. Cookie JWT (fallback — peut échouer au 1er render)
    try:
        token = cm.get(_COOKIE_NAME)
        if token:
            payload = _jwt_decode(token)
            if payload and payload.get("exp", 0) > time.time():
                session = {"username": payload["sub"], "roles": payload.get("roles", [])}
                # Re-créer une session serveur à partir du cookie
                expiry_days = max(1, int((payload["exp"] - time.time()) / 86400))
                new_sid = _store_session(session["username"], session["roles"], expiry_days)
                st.session_state["_auth_session"] = session
                st.session_state["_session_id"] = new_sid
                return session
    except Exception:
        pass
    return None


def has_role(session: dict | None, role: str) -> bool:
    return bool(session and role in session.get("roles", []))


def logout(cm) -> None:
    sid = st.session_state.get("_session_id", "")
    _delete_session(sid)
    for k in ("_auth_session", "_auth_step", "_auth_pending_user",
              "_auth_totp_new_secret", "_session_id"):
        st.session_state.pop(k, None)
    _delete_cookie(cm)


# ─────────────────────────────────────────────────────────────────────────────
# UI d'authentification
# ─────────────────────────────────────────────────────────────────────────────

def render_auth(cm) -> None:
    """
    Affiche le formulaire d'authentification adapté à l'étape courante.
    Gère : premier lancement, login, TOTP setup, TOTP verify.
    """
    cfg = load_users_config()
    users: dict = cfg.get("users", {})
    settings: dict = cfg.get("settings", {})
    expiry_days = int(settings.get("cookie_expiry_days", 7))

    # 1. Premier lancement : aucun compte
    has_users = any(u.get("password_hash") for u in users.values())
    if not has_users:
        _render_first_setup(cfg, cm)
        return

    step = st.session_state.get("_auth_step", "login")
    pending_user = st.session_state.get("_auth_pending_user", "")

    if step == "totp_setup" and pending_user:
        _render_totp_setup(pending_user, cfg, cm, expiry_days)
        return

    if step == "totp_verify" and pending_user:
        _render_totp_verify(pending_user, cfg, cm, expiry_days)
        return

    # 2. Formulaire login
    _centered_open()
    st.markdown("### 🔐 Atlas Trader")

    with st.form("atlas_login", clear_on_submit=False):
        username = st.text_input("Identifiant")
        password = st.text_input("Mot de passe", type="password")
        submitted = st.form_submit_button("Connexion", use_container_width=True, type="primary")

    if submitted:
        user = users.get(username)
        if not user or not _verify_password(password, user.get("password_hash", "")):
            st.error("Identifiant ou mot de passe incorrect.")
            _centered_close()
            return

        roles = user.get("roles", [])
        st.session_state["_auth_pending_user"] = username

        # Admin → TOTP obligatoire
        if "back" in roles and user.get("totp_enabled", True):
            st.session_state["_auth_step"] = (
                "totp_setup" if not user.get("totp_secret") else "totp_verify"
            )
            st.rerun()
            return

        # Utilisateur front-only → connexion directe sans 2FA
        _finalize_login(username, roles, cm, expiry_days)

    _centered_close()


def _render_first_setup(cfg: dict, cm) -> None:
    """Formulaire de création du compte admin lors du premier lancement."""
    _centered_open()
    st.markdown("### ⚙️ Configuration initiale — Atlas Trader")
    st.info(
        "Aucun utilisateur configuré. "
        "Créez votre compte **administrateur** ci-dessous."
    )
    with st.form("first_setup"):
        username = st.text_input("Identifiant admin", value="admin")
        pwd1 = st.text_input("Mot de passe (min. 8 caractères)", type="password")
        pwd2 = st.text_input("Confirmer le mot de passe", type="password")
        submitted = st.form_submit_button("Créer le compte", type="primary", use_container_width=True)

    if submitted:
        if len(pwd1) < 8:
            st.error("Le mot de passe doit contenir au moins 8 caractères.")
        elif pwd1 != pwd2:
            st.error("Les mots de passe ne correspondent pas.")
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
            st.success(f"✅ Compte '{username}' créé. La prochaine connexion configurera le 2FA.")
            st.rerun()

    _centered_close()


def _render_totp_setup(username: str, cfg: dict, cm, expiry_days: int) -> None:
    """Configuration TOTP initiale : génère et affiche le QR code."""
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

    _centered_open(width=500)
    st.markdown("### 📱 Configuration 2FA — Google Authenticator")
    st.info(
        "**Première connexion admin.** "
        "Scannez ce QR code avec votre application d'authentification, "
        "puis entrez le code à 6 chiffres pour confirmer."
    )
    col_qr, col_info = st.columns([1, 1])
    with col_qr:
        st.image(buf, width=190)
    with col_info:
        st.markdown("**Clé à saisir manuellement :**")
        st.code(secret, language=None)
        st.caption("Compatible : Google Authenticator · Authy · Bitwarden · 1Password")

    with st.form("totp_setup_form"):
        code = st.text_input("Code à 6 chiffres", max_chars=6, placeholder="123456")
        submitted = st.form_submit_button("Confirmer", type="primary", use_container_width=True)

    if submitted:
        if pyotp.TOTP(secret).verify(code, valid_window=1):
            users = cfg.get("users", {})
            users[username]["totp_secret"] = secret
            users[username]["totp_enabled"] = True
            save_users_config(cfg)
            st.session_state.pop("_auth_totp_new_secret", None)
            st.session_state.pop("_auth_step", None)
            roles = users[username].get("roles", [])
            _finalize_login(username, roles, cm, expiry_days)
        else:
            st.error("Code incorrect. Vérifiez que l'heure de votre téléphone est correcte.")

    _centered_close()


def _render_totp_verify(username: str, cfg: dict, cm, expiry_days: int) -> None:
    """Vérification TOTP lors d'une connexion normale."""
    import pyotp

    users = cfg.get("users", {})
    _centered_open(width=380)
    st.markdown("### 🔐 Vérification 2FA")
    st.caption(f"Compte : **{username}**")

    with st.form("totp_verify_form"):
        code = st.text_input(
            "Code à 6 chiffres",
            max_chars=6,
            placeholder="123456",
            autocomplete="one-time-code",
        )
        col_a, col_b = st.columns([3, 1])
        with col_a:
            submitted = st.form_submit_button("Vérifier", type="primary", use_container_width=True)
        with col_b:
            back = st.form_submit_button("← Retour", use_container_width=True)

    if back:
        st.session_state.pop("_auth_step", None)
        st.session_state.pop("_auth_pending_user", None)
        st.rerun()

    if submitted:
        user = users.get(username, {})
        if pyotp.TOTP(user["totp_secret"]).verify(code, valid_window=1):
            st.session_state.pop("_auth_step", None)
            roles = user.get("roles", [])
            _finalize_login(username, roles, cm, expiry_days)
        else:
            st.error("Code incorrect ou expiré. Réessayez.")

    _centered_close()


def _finalize_login(username: str, roles: list[str], cm, expiry_days: int) -> None:
    """Finalise la connexion : crée la session serveur + cookie + rerun."""
    session = {"username": username, "roles": roles}
    st.session_state["_auth_session"] = session
    st.session_state["admin_authenticated"] = "back" in roles  # compatibilité legacy
    st.session_state.pop("_auth_pending_user", None)
    st.session_state.pop("_auth_step", None)
    # Session serveur — survive aux rechargements de page via ?_sid= dans les URLs
    session_id = _store_session(username, roles, expiry_days)
    st.session_state["_session_id"] = session_id
    # Cookie — backup pour accès direct (ex: bookmark sans _sid)
    _write_cookie(cm, username, roles, expiry_days)
    logger.info(f"Login: {username} roles={roles} sid={session_id[:8]}…")
    # Naviguer vers le panneau admin avec _sid dans l'URL
    st.query_params["_sid"] = session_id
    st.query_params["admin"] = "1"
    st.rerun()


def _centered_open(width: int = 440) -> None:
    st.markdown(
        f'<div style="max-width:{width}px;margin:60px auto;">',
        unsafe_allow_html=True,
    )


def _centered_close() -> None:
    st.markdown("</div>", unsafe_allow_html=True)


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
        "Gestion des utilisateurs</h4>",
        unsafe_allow_html=True,
    )

    # ── Paramètres globaux ──────────────────────────────────────────────────
    st.markdown("**Paramètres de session**")
    col1, col2 = st.columns(2)
    with col1:
        settings["guest_mode"] = st.toggle(
            "Mode invité (front visible sans connexion)",
            value=settings.get("guest_mode", True),
            help="Si activé, le front est accessible sans login. "
                 "Le back-office nécessite toujours une authentification.",
        )
    with col2:
        settings["cookie_expiry_days"] = st.number_input(
            "Durée de session (jours)",
            min_value=1,
            max_value=90,
            value=int(settings.get("cookie_expiry_days", 7)),
            help="Durée de vie du cookie de session.",
        )
    cfg["settings"] = settings
    st.markdown("---")

    # ── Liste des utilisateurs ───────────────────────────────────────────────
    st.markdown("**Utilisateurs configurés**")
    if not users:
        st.info("Aucun utilisateur. L'assistant de création s'affiche à la prochaine connexion.")
    else:
        for uname, udata in list(users.items()):
            with st.expander(f"👤 {uname} — rôles : {', '.join(udata.get('roles', []))}"):
                roles = udata.get("roles", [])
                col_r1, col_r2 = st.columns(2)
                with col_r1:
                    has_front = st.toggle("Accès Front", value="front" in roles, key=f"front_{uname}")
                with col_r2:
                    has_back = st.toggle(
                        "Accès Back-office (+ 2FA obligatoire)",
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
                st.markdown("**Changer le mot de passe**")
                with st.form(f"reset_pwd_{uname}"):
                    new_pwd = st.text_input("Nouveau mot de passe", type="password", key=f"npwd_{uname}")
                    if st.form_submit_button("Mettre à jour", key=f"btn_pwd_{uname}"):
                        if len(new_pwd) >= 8:
                            udata["password_hash"] = hash_password(new_pwd)
                            st.success("Mot de passe mis à jour.")
                        else:
                            st.error("Minimum 8 caractères.")

                # Reset TOTP
                if udata.get("totp_secret"):
                    if st.button(
                        "🔄 Réinitialiser le 2FA (nouveau QR code à la prochaine connexion)",
                        key=f"reset_totp_{uname}",
                    ):
                        udata["totp_secret"] = ""
                        st.success("2FA réinitialisé — l'utilisateur devra re-scanner le QR code.")

                # Supprimer utilisateur
                if st.button(f"🗑 Supprimer {uname}", key=f"del_{uname}", type="secondary"):
                    del cfg["users"][uname]
                    save_users_config(cfg)
                    st.success(f"Utilisateur '{uname}' supprimé.")
                    st.rerun()

                users[uname] = udata

    st.markdown("---")

    # ── Ajouter un utilisateur ───────────────────────────────────────────────
    st.markdown("**Ajouter un utilisateur**")
    with st.form("add_user"):
        col1, col2 = st.columns(2)
        with col1:
            new_username = st.text_input("Identifiant")
            new_pwd1 = st.text_input("Mot de passe", type="password")
            new_pwd2 = st.text_input("Confirmer", type="password")
        with col2:
            role_front = st.toggle("Accès Front", value=True, key="new_front")
            role_back = st.toggle("Accès Back-office (+ 2FA)", value=False, key="new_back")
        submitted = st.form_submit_button("Ajouter", type="primary")

    if submitted:
        if not new_username:
            st.error("L'identifiant est obligatoire.")
        elif new_username in users:
            st.error(f"L'utilisateur '{new_username}' existe déjà.")
        elif len(new_pwd1) < 8:
            st.error("Minimum 8 caractères.")
        elif new_pwd1 != new_pwd2:
            st.error("Les mots de passe ne correspondent pas.")
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
            st.success(f"✅ Utilisateur '{new_username}' créé avec les rôles : {new_roles}")
            st.rerun()

    # Sauvegarder les modifications (rôles, settings)
    st.markdown("---")
    if st.button("💾 Sauvegarder les modifications", type="primary", use_container_width=True):
        cfg["users"] = users
        save_users_config(cfg)
        st.success("✅ Configuration utilisateurs sauvegardée.")
