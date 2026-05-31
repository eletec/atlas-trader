"""
quant/config.py — Source unique de vérité pour tous les hyperparamètres quant.

Lit la section `quant:` de config/settings.yaml.
Toutes les valeurs ont un défaut en dur ici (fallback si settings.yaml absent).
Aucun autre module quant/ ne doit définir ses propres constantes numériques.

Usage :
    from quant.config import get_quant_cfg

    cfg = get_quant_cfg()
    print(cfg.timeframe)          # "5m"
    print(cfg.fraction_per_trade) # 0.0075
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, fields
from pathlib import Path

logger = logging.getLogger("zeitgeist.quant.config")

# ─── Correspondance timeframe → barres / jour ────────────────────────────────
_TF_BARS_PER_DAY: dict[str, int] = {
    "1m": 1440, "3m": 480, "5m": 288, "15m": 96,
    "30m": 48,  "1h": 24,  "2h": 12,  "4h": 6, "1d": 1,
}


def bars_per_day(timeframe: str) -> int:
    return _TF_BARS_PER_DAY.get(timeframe.lower(), 288)


def bars_per_year(timeframe: str) -> int:
    return bars_per_day(timeframe) * 365


@dataclass
class QuantConfig:
    """Tous les hyperparamètres quant V2, lus depuis settings.yaml → quant:"""

    # ── Données ────────────────────────────────────────────────────────────
    symbol: str            = "BTC/USDT"
    timeframe: str         = "5m"
    history_days: int      = 90

    # ── Pipeline ───────────────────────────────────────────────────────────
    horizon_bars: int      = 4
    norm_window_days: int  = 30      # fenêtre normalisation en JOURS (converti × bars_per_day)
    p_up_threshold: float  = 0.58
    p_dn_threshold: float  = 0.42
    train_fraction: float  = 0.70
    refit_interval_days: int = 7

    # ── Signal model ───────────────────────────────────────────────────────
    use_hmm: bool          = True
    use_lgb: bool          = False
    signal_C: float        = 1.0
    signal_model_C: float          = 5.0   # régularisation LogReg (C↑ = moins régularisé = sorties plus étalées)
    signal_model_cv_folds: int     = 3     # folds TimeSeriesSplit (3 au lieu de 5 = moins de lissage)
    signal_model_calibrate: bool   = True  # Platt calibration ON
    use_barrier_label: bool        = False  # True → label TP/SL barrier (aligne signal + trade mgmt)
    barrier_max_horizon: int       = 96    # barres max pour résolution barrière (indépendant de horizon_bars)

    # ── Régime HMM ─────────────────────────────────────────────────────────
    hmm_n_states: int      = 3
    hmm_adx_threshold: float = 25.0

    # ── Risk management ────────────────────────────────────────────────────
    fraction_per_trade: float       = 0.0075
    stop_loss_atr_mult: float       = 2.5
    take_profit_atr_mult: float     = 3.5
    trailing_activation_atr: float  = 1.5   # was 1.0 — consensus 3 IA : laisser les trades respirer
    trailing_distance_atr: float    = 1.5   # was 1.0 — recommandation 1.5-2.0×ATR
    weekly_dd_kill_switch: float    = 0.08
    kill_switch_pause_days: int     = 7

    # ── Backtest ───────────────────────────────────────────────────────────
    initial_capital: float  = 10_000.0
    fee_rate: float         = 0.0005
    slippage_rate: float    = 0.0002

    # ── Walk-forward refit continu (pipeline rolling) ──────────────────────
    walk_fwd_every: int     = 0    # 0 = désactivé ; >0 = refit tous les N bars de test
    walk_fwd_window: int    = 720  # taille de la fenêtre train glissante en bars (défaut: 30j×24h)

    # ── Walk-forward (évaluation périodique legacy) ─────────────────────────
    wf_train_days: int      = 90
    wf_test_days: int       = 30
    wf_step_days: int       = 30
    wf_min_folds: int       = 12
    wf_max_folds: int       = 24
    wf_perm_iter: int       = 500

    # ── Mean-reverting RANGE trading ───────────────────────────────────────
    range_enabled: bool            = True   # False → désactive tout le range trading (audit 3 IA)
    range_sl_atr_mult: float       = 1.5    # SL en régime RANGE (plus serré qu'en TREND)
    range_tp_atr_mult: float       = 1.5    # TP symétrique → R:R = 1.0
    range_fraction_mult: float     = 0.50   # fraction du sizing TREND (50% par défaut)
    range_bb_long_threshold: float  = 0.10  # bb_pct_b < X → signal LONG range
    range_bb_short_threshold: float = 0.90  # bb_pct_b > X → signal SHORT range
    range_vwap_conf: float         = 0.30   # |vwap_dist| > X pour confirmation VWAP

    # ── Critères go-live (durcis après consensus 3 IA) ─────────────────────
    go_live_sharpe_min: float        = 0.80  # was 0.5 — trop permissif sur intraday bruité
    go_live_pf_min: float            = 1.30  # was 1.2
    go_live_trades_min: int          = 250
    go_live_pvalue_max: float        = 0.05  # was 0.10 — consensus Grok/GPT/DeepSeek
    go_live_positive_folds_pct: float = 0.65 # was 0.60

    # ── Sources de données (Q11/Q12) ───────────────────────────────────────
    data_provider: str               = "auto"  # "auto" | "twelve_data" | "yahoo"

    # ── Features avancées (Q13/Q14/Q15) ───────────────────────────────────
    use_dxy_feature: bool            = True    # Q14 : DXY comme feature inter-marché
    use_order_flow_features: bool    = True    # Q15 : funding rate + open interest + CVD
    use_regime_experts: bool         = False   # V3  : Mixture-of-Experts par état HMM

    # ── Horizon sweep (Q3) ─────────────────────────────────────────────────
    horizon_sweep_values: list       = field(default_factory=lambda: [2, 4, 8, 12])

    # ── Refit adaptatif KS-test (Q17) ──────────────────────────────────────
    refit_trigger: str               = "schedule"  # "schedule" | "ks_test" | "both"
    refit_ks_pvalue_threshold: float = 0.05        # seuil KS-test
    refit_ks_window_days: int        = 14          # fenêtre récente (jours)

    # ── Pipeline DAILY (FX/métaux) ─────────────────────────────────────────
    daily_active_assets: list        = field(default_factory=list)
    daily_history_days: int          = 1825   # ~5 ans de données journalières
    daily_horizon_bars: int          = 5      # direction dans 5 jours (1 semaine)
    daily_norm_window_days: int      = 252    # 1 an boursier pour normalisation
    daily_refit_interval_days: int   = 7      # refit hebdomadaire
    daily_execution_hour_utc: int    = 18     # heure d'exécution (18h UTC = clôture US)
    daily_p_up_threshold: float      = 0.57
    daily_p_dn_threshold: float      = 0.43

    # ── Propriétés dérivées ────────────────────────────────────────────────
    @property
    def norm_window_bars(self) -> int:
        """Fenêtre de normalisation convertie en barres selon le timeframe."""
        return self.norm_window_days * bars_per_day(self.timeframe)

    @property
    def refit_interval_seconds(self) -> int:
        return self.refit_interval_days * 86400

    @property
    def bars_per_year(self) -> int:
        return bars_per_year(self.timeframe)


# ─── Loader ──────────────────────────────────────────────────────────────────

_CACHE: QuantConfig | None = None


def get_quant_cfg(reload: bool = False) -> QuantConfig:
    """Retourne le singleton QuantConfig chargé depuis settings.yaml.

    Args:
        reload: True pour forcer le rechargement depuis le disque.
    """
    global _CACHE
    if _CACHE is not None and not reload:
        return _CACHE
    _CACHE = _load()
    return _CACHE


def _load() -> QuantConfig:
    """Charge settings.yaml et construit QuantConfig."""
    try:
        from utils.config import load_settings
        raw = load_settings()
        quant_raw: dict = raw.get("quant", {})
    except Exception as exc:
        logger.warning(f"Impossible de lire settings.yaml ({exc}) — valeurs par défaut utilisées.")
        return QuantConfig()

    # Mapper les clés yaml → champs dataclass (types forcés)
    kwargs: dict = {}
    field_types = {f.name: f.type for f in fields(QuantConfig)}
    for key, val in quant_raw.items():
        if key not in field_types:
            continue
        # Conversion de type simple (str, int, float, bool)
        try:
            type_hint = field_types[key]
            if type_hint in ("int", int):
                kwargs[key] = int(val)
            elif type_hint in ("float", float):
                kwargs[key] = float(val)
            elif type_hint in ("bool", bool):
                kwargs[key] = bool(val)
            else:
                kwargs[key] = val
        except (ValueError, TypeError) as exc:
            logger.warning(f"quant.{key} : conversion échouée ({exc}) — valeur par défaut.")

    cfg = QuantConfig(**kwargs)
    logger.info(
        f"QuantConfig chargé — {cfg.symbol} {cfg.timeframe} "
        f"| horizon={cfg.horizon_bars}b "
        f"| P_up>{cfg.p_up_threshold} P_dn<{cfg.p_dn_threshold} "
        f"| SL={cfg.stop_loss_atr_mult}×ATR TP={cfg.take_profit_atr_mult}×ATR "
        f"| frac={cfg.fraction_per_trade:.2%}"
    )
    return cfg


def save_quant_cfg(cfg: QuantConfig) -> None:
    """Persiste les champs de QuantConfig dans la section quant: de settings.yaml.

    Ne touche pas aux autres sections du fichier.
    """
    try:
        from utils.config import load_settings, save_settings
        raw = load_settings()
    except Exception as exc:
        raise RuntimeError(f"Impossible de charger settings.yaml : {exc}") from exc

    # Reconstruire la section quant depuis le dataclass
    quant_dict: dict = {}
    for f in fields(cfg):
        quant_dict[f.name] = getattr(cfg, f.name)
    raw["quant"] = quant_dict

    from utils.config import save_settings
    save_settings(raw)

    # Invalider le cache singleton
    global _CACHE
    _CACHE = None
    logger.info("QuantConfig sauvegardé dans settings.yaml")


# ─── Clé API Twelve Data ─────────────────────────────────────────────────────

def get_twelve_data_key() -> str:
    """Retourne la clé API Twelve Data (priorisé : env → secrets.yaml → "").

    Ordre de recherche :
    1. Variable d'environnement ``TWELVE_DATA_KEY``
    2. ``config/secrets.yaml → data.twelve_data_key``
    3. ``config/settings.yaml → data.twelve_data_key`` (override local optionnel)
    4. Chaîne vide (provider Yahoo en fallback)
    """
    import os

    # 1. Variable d'environnement
    env_key = os.environ.get("TWELVE_DATA_KEY", "").strip()
    if env_key:
        return env_key

    # 2. config/secrets.yaml (gitignored)
    secrets_path = Path(__file__).resolve().parent.parent / "config" / "secrets.yaml"
    if secrets_path.exists():
        try:
            import yaml
            with secrets_path.open("r", encoding="utf-8") as fh:
                secrets = yaml.safe_load(fh) or {}
            key = str(secrets.get("data", {}).get("twelve_data_key", "")).strip()
            if key:
                return key
        except Exception as exc:
            logger.warning(f"Lecture config/secrets.yaml échouée : {exc}")

    # 3. settings.yaml → data.twelve_data_key (override local sans la clé vraie)
    try:
        from utils.config import load_settings
        raw = load_settings()
        key = str(raw.get("data", {}).get("twelve_data_key", "")).strip()
        if key:
            return key
    except Exception:
        pass

    return ""
