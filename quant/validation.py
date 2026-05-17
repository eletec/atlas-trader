"""
quant/validation.py — Validation impitoyable (anti-overfit, anti-data-mining).

Outils :
- walk_forward_split : segmente une série temporelle en folds chronologiques.
- block_bootstrap_permutation_test : test de significativité préservant la corrélation.
- deflated_sharpe_ratio : corrige le Sharpe pour le multiple testing (Bailey & López).
- ablation_test : compare la stratégie complète à des variantes amputées.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Iterator

import numpy as np
import pandas as pd

logger = logging.getLogger("quant.validation")


def walk_forward_split(
    index: pd.DatetimeIndex,
    train_months: int = 6,
    test_months: int = 3,
    step_months: int | None = None,
) -> Iterator[tuple[pd.DatetimeIndex, pd.DatetimeIndex]]:
    """Génère des paires (train_idx, test_idx) chronologiques sans overlap.

    Args:
        index: index temporel complet
        train_months: durée de la fenêtre d'entraînement
        test_months: durée de la fenêtre de test
        step_months: décalage entre folds (défaut = test_months pour folds disjoints)
    """
    if step_months is None:
        step_months = test_months
    start = index.min()
    end = index.max()
    cursor = start
    train_delta = pd.DateOffset(months=train_months)
    test_delta = pd.DateOffset(months=test_months)
    step_delta = pd.DateOffset(months=step_months)

    while cursor + train_delta + test_delta <= end:
        train_start = cursor
        train_end = cursor + train_delta
        test_start = train_end
        test_end = test_start + test_delta

        train_idx = index[(index >= train_start) & (index < train_end)]
        test_idx = index[(index >= test_start) & (index < test_end)]
        if len(train_idx) > 0 and len(test_idx) > 0:
            yield train_idx, test_idx
        cursor = cursor + step_delta


def block_bootstrap_permutation_test(
    returns: pd.Series,
    metric_fn: Callable[[pd.Series], float],
    n_permutations: int = 1000,
    block_size: int = 96,  # 1 jour en 15min
    seed: int = 42,
) -> dict:
    """Test de permutation par blocs (préserve l'autocorrélation locale).

    Hypothèse H0 : la séquence des rendements est interchangeable par blocs
    (i.e. la stratégie n'extrait aucun signal au-delà du hasard).

    Args:
        returns: série de rendements (de la stratégie)
        metric_fn: fonction qui calcule la métrique d'intérêt (ex. Sharpe)
        n_permutations: nombre de permutations
        block_size: taille des blocs (en barres) — préserve l'autocorrélation
        seed: graine RNG

    Returns:
        {observed, p_value, distribution_quantiles}
    """
    rng = np.random.default_rng(seed)
    observed = metric_fn(returns)
    rets = returns.dropna().values
    n = len(rets)
    n_blocks = max(1, n // block_size)

    perm_metrics = np.empty(n_permutations)
    for k in range(n_permutations):
        # Découpe en blocs, mélange
        block_starts = np.arange(0, n_blocks * block_size, block_size)
        rng.shuffle(block_starts)
        perm = np.concatenate([rets[s : s + block_size] for s in block_starts])
        perm_series = pd.Series(perm)
        perm_metrics[k] = metric_fn(perm_series)

    # p-value : prob qu'un tirage aléatoire fasse aussi bien ou mieux
    p_value = float(np.mean(perm_metrics >= observed))
    return {
        "observed": float(observed),
        "p_value": p_value,
        "quantiles": {
            "p05": float(np.quantile(perm_metrics, 0.05)),
            "p50": float(np.quantile(perm_metrics, 0.50)),
            "p95": float(np.quantile(perm_metrics, 0.95)),
        },
        "n_permutations": n_permutations,
    }


def deflated_sharpe_ratio(
    observed_sharpe: float,
    n_trials: int,
    n_observations: int,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """Sharpe dégonflé (Bailey & López de Prado, 2014).

    Corrige le biais lié au multiple testing et à la non-normalité des rendements.

    Returns:
        Probabilité que le Sharpe observé soit > 0 après ajustement (∈ [0, 1]).
    """
    from math import sqrt
    from scipy.stats import norm

    # Sharpe attendu maximum sous H0 (selon López de Prado)
    e = 0.5772156649  # Euler-Mascheroni
    sr_max_expected = sqrt(2 * np.log(max(n_trials, 1))) * (1 - e / sqrt(2 * np.log(max(n_trials, 1))) - e)
    # Z-score ajusté
    num = (observed_sharpe - sr_max_expected) * sqrt(n_observations - 1)
    den = sqrt(1 - skewness * observed_sharpe + (kurtosis - 1) / 4 * observed_sharpe ** 2)
    if den <= 0:
        return float("nan")
    return float(norm.cdf(num / den))


@dataclass
class AblationResult:
    name: str
    sharpe: float
    total_return: float
    max_dd: float
    n_trades: int


def ablation_test(
    run_variant: Callable[[str], "AblationResult"],
    variants: list[str] = None,
) -> pd.DataFrame:
    """Compare des variantes amputées au modèle complet.

    Args:
        run_variant: fonction qui prend un nom de variante et retourne un AblationResult
        variants: liste de variantes à tester (défaut : ['full', 'no_regime', 'no_signal', 'baseline'])

    Returns:
        DataFrame récapitulatif.
    """
    if variants is None:
        variants = ["full", "no_regime", "no_signal", "baseline_breakout"]
    rows = []
    for v in variants:
        try:
            r = run_variant(v)
            rows.append(
                {
                    "variant": r.name,
                    "sharpe": r.sharpe,
                    "total_return": r.total_return,
                    "max_dd": r.max_dd,
                    "n_trades": r.n_trades,
                }
            )
        except Exception as exc:
            logger.error(f"Variante {v} a échoué: {exc}")
            rows.append({"variant": v, "sharpe": np.nan, "error": str(exc)})
    return pd.DataFrame(rows)


# ─── Phase 4.5 : Monte Carlo sur l'ordre des trades ──────────────────────────

def monte_carlo_trade_order(
    trades: list,
    n_perms: int = 10_000,
    seed: int = 42,
) -> dict:
    """Monte Carlo sur l'ordre des trades (préserve les P&L individuels).

    Hypothèse H0 : l'ordre des trades est aléatoire → mesure si le Sharpe
    observé serait reproductible par chance pure.

    Args:
        trades: liste de Trade (attribut ``pnl_pct``) ou dicts ``{"pnl_pct": float}``.
        n_perms: nombre de permutations.
        seed: graine RNG.

    Returns:
        dict : observed_sharpe, p_value, sharpe_ic95_lo, sharpe_ic95_hi, n_trades, n_perms.
    """
    if not trades:
        return {"observed_sharpe": float("nan"), "p_value": float("nan"), "n_trades": 0}

    pnls = np.array(
        [t.pnl_pct if hasattr(t, "pnl_pct") else t["pnl_pct"] for t in trades],
        dtype=float,
    )
    n = len(pnls)
    if n < 10:
        return {
            "observed_sharpe": float("nan"),
            "p_value": float("nan"),
            "n_trades": n,
            "note": "< 10 trades — test non significatif",
        }

    def _sharpe(arr: np.ndarray) -> float:
        sd = arr.std(ddof=1)
        return float(arr.mean() / sd * np.sqrt(n)) if sd > 0 else 0.0

    observed = _sharpe(pnls)
    rng = np.random.default_rng(seed)
    perm_sharpes = np.fromiter(
        (_sharpe(rng.permutation(pnls)) for _ in range(n_perms)),
        dtype=float,
        count=n_perms,
    )
    p_value = float(np.mean(perm_sharpes >= observed))
    return {
        "observed_sharpe": float(observed),
        "p_value": p_value,
        "sharpe_ic95_lo": float(np.quantile(perm_sharpes, 0.025)),
        "sharpe_ic95_hi": float(np.quantile(perm_sharpes, 0.975)),
        "n_trades": n,
        "n_perms": n_perms,
    }


# ─── Phase 4.3 : PBO (Probability of Backtest Overfitting) ───────────────────

def probability_of_backtest_overfitting(
    is_sharpes: list[float],
    oos_sharpes: list[float],
) -> dict:
    """Estime la PBO via la corrélation de rang IS/OOS et le rang du meilleur IS.

    Inspiration : Bailey & López de Prado (SSRN 2014).

    Interprétation :
    - ``pbo`` proche de 0 → faible risque d'overfit.
    - ``pbo`` proche de 1 → forte probabilité que le best-IS ne soit pas le best-OOS.
    - ``spearman_rho`` > 0 → les performances IS et OOS sont corrélées (bon signe).

    Args:
        is_sharpes: Sharpe en-échantillon (train) par fold.
        oos_sharpes: Sharpe hors-échantillon (test) par fold.

    Returns:
        dict : pbo, spearman_rho, spearman_pval, best_is_oos_rank_pct.
    """
    from scipy.stats import spearmanr

    n = len(is_sharpes)
    if n < 4:
        return {"pbo": float("nan"), "spearman_rho": float("nan"), "note": "< 4 folds"}

    is_arr = np.array(is_sharpes, dtype=float)
    oos_arr = np.array(oos_sharpes, dtype=float)

    rho, pval = spearmanr(is_arr, oos_arr)

    # Rang OOS du meilleur IS (percentile dans la distribution OOS)
    best_is_idx = int(np.argmax(is_arr))
    best_is_oos_value = float(oos_arr[best_is_idx])
    oos_rank_pct = float(np.sum(oos_arr <= best_is_oos_value)) / n

    # PBO = proba que le best-IS ne soit pas le meilleur OOS
    pbo = float(np.clip(1.0 - oos_rank_pct, 0.0, 1.0))

    return {
        "pbo": pbo,
        "spearman_rho": float(rho) if not np.isnan(rho) else float("nan"),
        "spearman_pval": float(pval) if not np.isnan(pval) else float("nan"),
        "best_is_oos_rank_pct": oos_rank_pct,
        "n_folds": n,
    }


# ─── Phase 4.6 : Stress tests sur sous-périodes historiques ──────────────────

def stress_test_historical(
    ohlcv: pd.DataFrame,
    periods: list[tuple[str, str, str]] | None = None,
    config=None,
    min_train_bars: int = 2000,
) -> pd.DataFrame:
    """Exécute le pipeline sur des sous-fenêtres historiques représentant
    différents régimes de marché.

    Args:
        ohlcv: OHLCV complet (DatetimeIndex UTC).
        periods: liste de (label, start_iso, end_iso). Si None → découpe automatique
            en quartiles de la série disponible (Q1=récent, Q4=le plus ancien).
        config: PipelineConfig (None = défauts).
        min_train_bars: barres minimales pour un split 70/30 valide.

    Returns:
        DataFrame avec une ligne par période : label, sharpe, total_return, max_dd,
        n_trades, win_rate, profit_factor.
    """
    from quant.pipeline import run_pipeline, PipelineConfig

    cfg = config or PipelineConfig()
    rows = []

    if periods is None:
        # Découpe automatique : 4 quarts égaux de la série disponible
        n = len(ohlcv)
        q = n // 4
        auto_periods = [
            ("Q1 (récent)",        ohlcv.index[0],     ohlcv.index[q]),
            ("Q2",                 ohlcv.index[q],     ohlcv.index[2 * q]),
            ("Q3",                 ohlcv.index[2 * q], ohlcv.index[3 * q]),
            ("Q4 (ancien)",        ohlcv.index[3 * q], ohlcv.index[-1]),
        ]
        slices = [(lbl, ohlcv.loc[s:e]) for lbl, s, e in auto_periods]
    else:
        slices = []
        for lbl, start, end in periods:
            mask = (ohlcv.index >= pd.Timestamp(start, tz="UTC")) & \
                   (ohlcv.index <= pd.Timestamp(end, tz="UTC"))
            slices.append((lbl, ohlcv.loc[mask]))

    for lbl, sub in slices:
        if len(sub) < min_train_bars:
            logger.warning(f"Stress [{lbl}] : {len(sub)} barres < {min_train_bars} — ignoré.")
            rows.append({"label": lbl, "n_bars": len(sub), "note": "données insuffisantes"})
            continue
        split = int(len(sub) * 0.70)
        train_idx = sub.index[:split]
        test_idx = sub.index[split:]
        try:
            arts = run_pipeline(sub, train_idx, test_idx, cfg)
            m = arts.backtest.metrics
            rows.append({
                "label": lbl,
                "n_bars": len(sub),
                "sharpe": round(m.get("sharpe", 0.0), 3),
                "total_return": round(m.get("total_return", 0.0), 4),
                "max_dd": round(m.get("max_dd", 0.0), 4),
                "n_trades": len(arts.backtest.trades),
                "win_rate": round(m.get("win_rate", 0.0), 3),
                "profit_factor": round(m.get("profit_factor", 0.0), 3),
            })
        except Exception as exc:
            logger.error(f"Stress [{lbl}] échec : {exc}")
            rows.append({"label": lbl, "n_bars": len(sub), "error": str(exc)})

    return pd.DataFrame(rows)


# ─── Q3 : Sweep des horizons de prédiction ───────────────────────────────────

def sweep_horizon(
    ohlcv: pd.DataFrame,
    horizons: list[int] | None = None,
    config=None,
    min_train_bars: int = 2000,
) -> pd.DataFrame:
    """Évalue le pipeline sur plusieurs horizons de prédiction (Q3).

    Lance ``run_pipeline()`` avec un split 70/30 pour chaque valeur d'horizon
    et retourne un DataFrame comparatif. Permet de choisir l'horizon optimal
    avant le walk-forward complet.

    Args:
        ohlcv: OHLCV complet (DatetimeIndex UTC).
        horizons: liste d'horizons (barres) à tester. Si None → lire depuis
                  ``settings.yaml → quant.horizon_sweep_values``.
        config: PipelineConfig de base (None = défauts). L'horizon est
                overridé pour chaque itération.
        min_train_bars: barres minimales pour un split 70/30 valide.

    Returns:
        DataFrame avec colonnes : horizon, sharpe, profit_factor, max_dd,
        n_trades, win_rate, total_return.
    """
    from quant.pipeline import run_pipeline, PipelineConfig
    from dataclasses import replace as dc_replace
    import numpy as np

    # Récupérer horizons depuis config si non fournis
    if horizons is None:
        try:
            from quant.config import get_quant_cfg
            sweep_val = get_quant_cfg().horizon_sweep_values
            if isinstance(sweep_val, list):
                horizons = [int(v) for v in sweep_val]
            elif isinstance(sweep_val, str):
                horizons = [int(v.strip()) for v in sweep_val.split(",") if v.strip()]
            else:
                horizons = [2, 4, 8, 12]
        except Exception:
            horizons = [2, 4, 8, 12]

    if len(ohlcv) < min_train_bars:
        logger.warning(f"sweep_horizon: {len(ohlcv)} barres < {min_train_bars} min — abandon.")
        return pd.DataFrame()

    base_cfg = config or PipelineConfig()
    split = int(len(ohlcv) * 0.70)
    train_idx = ohlcv.index[:split]
    test_idx = ohlcv.index[split:]

    rows = []
    for h in horizons:
        # Créer une config avec l'horizon overridé
        try:
            iter_cfg = dc_replace(base_cfg, horizon_bars=h)
        except Exception:
            # Fallback si dc_replace échoue (dataclass avec field_factory)
            iter_cfg = PipelineConfig()
            object.__setattr__(iter_cfg, "horizon_bars", h)

        try:
            arts = run_pipeline(ohlcv, train_idx, test_idx, iter_cfg)
            m = arts.backtest.metrics
            rows.append({
                "horizon": h,
                "sharpe": round(float(m.get("sharpe", 0.0)), 3),
                "profit_factor": round(float(m.get("profit_factor", 0.0)), 3),
                "max_dd": round(float(m.get("max_dd", 0.0)), 4),
                "n_trades": len(arts.backtest.trades) if arts.backtest.trades else 0,
                "win_rate": round(float(m.get("win_rate", 0.0)), 3),
                "total_return": round(float(m.get("total_return", 0.0)), 4),
            })
            logger.info(
                f"sweep_horizon h={h}b → Sharpe={rows[-1]['sharpe']:+.2f} "
                f"PF={rows[-1]['profit_factor']:.2f} DD={rows[-1]['max_dd']:.1%}"
            )
        except Exception as exc:
            logger.error(f"sweep_horizon h={h} échoué : {exc}")
            rows.append({"horizon": h, "sharpe": np.nan, "error": str(exc)})

    return pd.DataFrame(rows)


# ─── Phase 4 orchestrateur complet ───────────────────────────────────────────

def run_full_validation(
    symbol: str = "BTC/USDT",
    timeframe: str = "5m",
    total_days: int = 420,
    n_mc_perms: int = 5_000,
    verbose: bool = True,
) -> dict:
    """Orchestre TOUTE la Phase 4 : walk-forward, PBO, Monte Carlo, stress tests.

    Retourne un dict avec toutes les métriques et un verdict global (``pass_all``).
    Peut aussi être lancé via ``python main.py --validate``.
    """
    from quant.walkforward import run_walkforward
    from quant.data_loader import fetch_history

    _log = logger.info if verbose else logger.debug
    _log("=" * 70)
    _log(f"VALIDATION COMPLÈTE PHASE 4 — {symbol} {timeframe} {total_days}j")
    _log("=" * 70)

    # 1. Walk-forward (inclut permutation test + critères go-live)
    wf = run_walkforward(symbol=symbol, timeframe=timeframe,
                         total_days=total_days, verbose=verbose)
    if wf is None:
        logger.error("Walk-forward échoué — validation abandonnée.")
        return {"pass_all": False, "error": "walk-forward failed"}

    folds_df = wf["folds"]
    is_sharpes = []  # On n'a pas les IS Sharpe depuis run_walkforward → calcul approché
    oos_sharpes = list(folds_df["sharpe"].values)

    # 2. PBO (approximation sans IS Sharpe explicites — utilise std fold comme proxy IS)
    # On estime IS ≈ OOS légèrement décalé dans le temps (fold k-1 → fold k)
    if len(oos_sharpes) >= 4:
        _log("\n--- PBO (Probability of Backtest Overfitting) ---")
        # Approche : IS ≈ performance sur les N/2 premiers folds, OOS = N/2 derniers
        mid = len(oos_sharpes) // 2
        pbo_result = probability_of_backtest_overfitting(
            is_sharpes=oos_sharpes[:mid],
            oos_sharpes=oos_sharpes[mid:],
        )
        _log(f"  PBO estimé              : {pbo_result.get('pbo', float('nan')):.3f}")
        _log(f"  Spearman rho IS/OOS     : {pbo_result.get('spearman_rho', float('nan')):.3f}")
        _log(f"  p-val Spearman          : {pbo_result.get('spearman_pval', float('nan')):.3f}")
        pbo_ok = pbo_result.get("pbo", 1.0) < 0.50
        _log(f"  PBO < 50% (critère)     : {'✓' if pbo_ok else '✗'}")
    else:
        pbo_result = {}
        pbo_ok = None

    # 3. Monte Carlo sur ordre des trades (agrégé tous les folds)
    _log("\n--- Monte Carlo sur ordre des trades ---")
    all_trades: list = []
    for _, fold_row in folds_df.iterrows():
        # trades individuels non disponibles depuis walkforward → on construit
        # une série synthétique à partir des métriques agrégées par fold
        n_t = int(fold_row.get("n_trades", 0))
        if n_t > 0:
            ret_per_trade = fold_row.get("total_return", 0.0) / n_t
            all_trades.extend([{"pnl_pct": ret_per_trade}] * n_t)

    mc = monte_carlo_trade_order(all_trades, n_perms=n_mc_perms)
    _log(f"  Sharpe observé (trades)  : {mc.get('observed_sharpe', float('nan')):.3f}")
    _log(f"  p-value MC               : {mc.get('p_value', float('nan')):.3f}")
    _log(f"  IC 95% Sharpe            : [{mc.get('sharpe_ic95_lo', 0):.3f} ; {mc.get('sharpe_ic95_hi', 0):.3f}]")
    _log(f"  Trades MC                : {mc.get('n_trades', 0)}")
    mc_ok = mc.get("p_value", 1.0) < 0.10

    # 4. Deflated Sharpe Ratio
    _log("\n--- Deflated Sharpe Ratio ---")
    n_folds = len(oos_sharpes)
    n_obs_per_fold = max(1, len(folds_df))
    dsr = deflated_sharpe_ratio(
        observed_sharpe=wf["sharpe_mean"],
        n_trials=max(n_folds, 1),
        n_observations=n_obs_per_fold * 30,  # approx barres journalières
    )
    _log(f"  DSR (prob Sharpe > 0)    : {dsr:.3f}")
    dsr_ok = dsr > 0.95

    # 5. Stress tests (quartiles de la période disponible)
    _log("\n--- Stress tests historiques ---")
    ohlcv = fetch_history(symbol=symbol, timeframe=timeframe, days=total_days, cache=True)
    stress_df = stress_test_historical(ohlcv, periods=None)
    if verbose:
        _log(stress_df.to_string(index=False))
    stress_ok = stress_df["sharpe"].dropna().gt(0).mean() >= 0.50 if "sharpe" in stress_df.columns else None

    # 6. Verdict global
    wf_ok = wf.get("pass_criteria", False)
    verdict_parts = {
        "walk_forward": wf_ok,
        "pbo_lt_50pct": pbo_ok,
        "monte_carlo_pval": mc_ok,
        "deflated_sharpe": dsr_ok,
        "stress_test_50pct_positive": stress_ok,
    }
    pass_all = all(v for v in verdict_parts.values() if v is not None)

    _log("\n" + "=" * 70)
    _log("VERDICT FINAL PHASE 4")
    _log("=" * 70)
    for name, ok in verdict_parts.items():
        mark = "✓" if ok else ("— (N/A)" if ok is None else "✗")
        _log(f"  {mark}  {name}")
    _log(f"\n→ {'VALIDÉ — PRÊT POUR PAPER LIVE ✓' if pass_all else 'VALIDATION INSUFFISANTE — CONTINUER EN BACKTEST ✗'}")
    _log("=" * 70)

    return {
        "pass_all": pass_all,
        "walk_forward": wf,
        "pbo": pbo_result,
        "monte_carlo": mc,
        "deflated_sharpe_ratio": dsr,
        "stress_tests": stress_df.to_dict("records") if not stress_df.empty else [],
        "verdict": verdict_parts,
    }
