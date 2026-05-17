"""
quant/pipeline.py — Pipeline complet bout en bout.

Compose toutes les briques en un seul appel : fetch → features → régime →
signal → décisions → backtest. Sert d'orchestrateur unique pour les tests
walk-forward et l'inférence live future.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Sequence

import pandas as pd

from quant.backtest import Backtester, BacktestResult, buy_and_hold
from quant.config import QuantConfig, get_quant_cfg
from quant.features import compute_features, make_target_direction
from quant.normalization import normalize_features
from quant.regime import RegimeDetector
from quant.risk import RiskManager, RiskParams
from quant.signal_model import SignalModel
from quant.strategy import Action, BaselineStrategy

logger = logging.getLogger("zeitgeist.quant.pipeline")


DEFAULT_FEATURE_COLS = [
    "log_return_1_q",
    "log_return_4_q",
    "log_return_24_q",
    "atr_pct_q",
    "adx_14_q",
    "dist_ma50_q",
    "volume_z_20_q",
    "vwap_dist_20_q",   # C.1 : VWAP distance / ATR (3/3 IA)
    "bb_pct_b_q",       # C.2 : Bollinger %b (GPT + DeepSeek)
    "obv_proxy_20_q",   # C.3 : OBV proxy rolling causal (Grok + DeepSeek)
    "hour_sin",       # calendaire — déjà ∈ [0,1], pas de normalisation _q
    "hour_cos",
    "is_weekend",
]


@dataclass
class PipelineConfig:
    """Paramètres du pipeline V2. Les valeurs par défaut sont chargées depuis
    settings.yaml → quant: via get_quant_cfg(). Ne jamais hardcoder ici."""
    horizon_bars: int           = field(default_factory=lambda: get_quant_cfg().horizon_bars)
    norm_window: int            = field(default_factory=lambda: get_quant_cfg().norm_window_bars)
    p_up_threshold: float       = field(default_factory=lambda: get_quant_cfg().p_up_threshold)
    p_dn_threshold: float       = field(default_factory=lambda: get_quant_cfg().p_dn_threshold)
    use_hmm: bool               = field(default_factory=lambda: get_quant_cfg().use_hmm)
    use_signal_model: bool      = True
    feature_cols: Sequence[str] = field(default_factory=lambda: list(DEFAULT_FEATURE_COLS))
    initial_capital: float      = field(default_factory=lambda: get_quant_cfg().initial_capital)
    fee_rate: float             = field(default_factory=lambda: get_quant_cfg().fee_rate)
    slippage_rate: float        = field(default_factory=lambda: get_quant_cfg().slippage_rate)

    @classmethod
    def from_quant_cfg(cls, qcfg: QuantConfig | None = None) -> "PipelineConfig":
        """Construit explicitement depuis un QuantConfig (utile pour les tests)."""
        c = qcfg or get_quant_cfg()
        return cls(
            horizon_bars=c.horizon_bars,
            norm_window=c.norm_window_bars,
            p_up_threshold=c.p_up_threshold,
            p_dn_threshold=c.p_dn_threshold,
            use_hmm=c.use_hmm,
            initial_capital=c.initial_capital,
            fee_rate=c.fee_rate,
            slippage_rate=c.slippage_rate,
        )

    @classmethod
    def from_asset_config(cls, asset: str) -> "PipelineConfig":
        """Construit depuis ``config/assets/{slug}.yaml`` (section ``v2_risk``).

        Lit les overrides propres à l'actif (SL/TP mult, fraction, capital)
        et fusionne avec les valeurs globales de ``settings.yaml → quant:``.
        Si le fichier YAML n'existe pas, retourne les valeurs globales.

        Args:
            asset: ex. ``"BTC/USDT"``, ``"XAU/USD"``
        """
        base = cls.from_quant_cfg()
        try:
            slug = asset.replace("/", "_")
            yaml_path = (
                __import__("pathlib").Path(__file__).resolve().parent.parent
                / "config" / "assets" / f"{slug}.yaml"
            )
            if not yaml_path.exists():
                return base
            import yaml
            with yaml_path.open("r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            v2r = raw.get("v2_risk", {})
            cb = raw.get("circuit_breaker", {})
            # Capital paper spécifique à l'actif
            capital = float(raw.get("paper_capital_usd", base.initial_capital))
            # Risk params
            sl_mult = float(v2r.get("stop_loss_atr_mult", base.stop_loss_atr_mult
                                    if hasattr(base, "stop_loss_atr_mult") else 2.5))
            tp_mult = float(v2r.get("take_profit_atr_mult", base.take_profit_atr_mult
                                    if hasattr(base, "take_profit_atr_mult") else 3.5))
            frac = float(v2r.get("fraction_per_trade", base.fraction_per_trade
                                 if hasattr(base, "fraction_per_trade") else 0.0075))
            # Rebuild avec overrides asset
            qcfg = get_quant_cfg()
            overridden = cls(
                horizon_bars=qcfg.horizon_bars,
                norm_window=qcfg.norm_window_bars,
                p_up_threshold=qcfg.p_up_threshold,
                p_dn_threshold=qcfg.p_dn_threshold,
                use_hmm=qcfg.use_hmm,
                initial_capital=capital,
                fee_rate=qcfg.fee_rate,
                slippage_rate=qcfg.slippage_rate,
            )
            return overridden
        except Exception as exc:
            logger.warning(f"from_asset_config({asset}) fallback globaux : {exc}")
            return base


@dataclass
class PipelineArtifacts:
    features: pd.DataFrame
    features_norm: pd.DataFrame
    regime: pd.Series
    proba_up: pd.Series
    actions: pd.Series
    backtest: BacktestResult


def run_pipeline(
    ohlcv: pd.DataFrame,
    train_idx: pd.DatetimeIndex,
    test_idx: pd.DatetimeIndex,
    config: PipelineConfig | None = None,
) -> PipelineArtifacts:
    """Exécute pipeline sur train (fit) puis test (predict + backtest).

    Args:
        ohlcv: OHLCV complet couvrant train + test
        train_idx: index des barres d'entraînement
        test_idx: index des barres de test (OOS)
        config: configuration

    Returns:
        Artefacts pipeline + résultat backtest sur test_idx uniquement.
    """
    cfg = config or PipelineConfig()

    # 1. Features (sur tout l'historique pour éviter cold start sur test)
    feats_raw = compute_features(ohlcv)
    feats_norm = normalize_features(
        feats_raw,
        window=cfg.norm_window,
        columns=["log_return_1", "log_return_4", "log_return_24",
                 "atr_pct", "adx_14", "dist_ma50", "volume_z_20", "vol_of_vol_20",
                 "vwap_dist_20", "bb_pct_b", "obv_proxy_20"],
    )
    feats = pd.concat([feats_raw, feats_norm], axis=1)

    # 2. Détecteur de régime — FIT sur train uniquement
    regime = RegimeDetector(use_hmm=cfg.use_hmm).fit(feats.loc[train_idx])
    regime_series = regime.predict(feats)

    # 3. Modèle de signal — FIT sur train uniquement
    proba_up = pd.Series(index=feats.index, dtype="float64")
    if cfg.use_signal_model:
        y = make_target_direction(ohlcv, horizon=cfg.horizon_bars)
        # B.3 Warmup : exclure les premières norm_window barres (quantile instable — 3/3 IA)
        warmup_cutoff = feats.index[min(cfg.norm_window, len(feats) - 1)]
        sm_train_idx = train_idx[train_idx >= warmup_cutoff]
        X_train = feats.loc[sm_train_idx, cfg.feature_cols]
        y_train = y.loc[sm_train_idx]
        # Exclure les barres dont la cible n'est pas observable (fin de train)
        valid = X_train.notna().all(axis=1) & y_train.notna()
        try:
            model = SignalModel(feature_cols=cfg.feature_cols).fit(
                X_train.loc[valid], y_train.loc[valid]
            )
            proba_up = model.predict_proba(feats[cfg.feature_cols])
        except Exception as exc:
            logger.error(f"SignalModel échec ({exc}) — fallback P=0.5.")
            proba_up.loc[:] = 0.5
    else:
        proba_up.loc[:] = 0.5

    # 4. Décisions vectorisées — équivalent strict à decide() mais O(1) numpy
    trending_mask = (regime_series == 1.0).fillna(False)
    proba_valid   = proba_up.notna()
    actions = pd.Series(Action.FLAT, index=feats.index, dtype="object")
    long_mask  = trending_mask & proba_valid & (proba_up > cfg.p_up_threshold)
    short_mask = trending_mask & proba_valid & (proba_up < cfg.p_dn_threshold)
    actions[long_mask]  = Action.LONG
    actions[short_mask] = Action.SHORT

    # 5. Backtest sur test_idx uniquement
    test_ohlcv = ohlcv.loc[test_idx]
    test_actions = actions.loc[test_idx]
    test_atr = feats["atr_14"].loc[test_idx]

    bt = Backtester(
        initial_capital=cfg.initial_capital,
        fee_rate=cfg.fee_rate,
        slippage_rate=cfg.slippage_rate,
        risk_manager=RiskManager(RiskParams()),
    )
    result = bt.run(test_ohlcv, test_actions, test_atr)

    return PipelineArtifacts(
        features=feats_raw,
        features_norm=feats_norm,
        regime=regime_series,
        proba_up=proba_up,
        actions=actions,
        backtest=result,
    )


def run_baseline(ohlcv: pd.DataFrame) -> BacktestResult:
    """Stratégie baseline ultra-simple (breakout Donchian) sans modèle ni régime."""
    feats = compute_features(ohlcv)
    actions = BaselineStrategy().signals(feats)
    bt = Backtester()
    return bt.run(ohlcv, actions, feats["atr_14"])
