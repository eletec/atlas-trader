"""
v7/core/carry_scanner.py — Scanner dynamique de l'univers Funding Carry.

Détecte automatiquement tous les couples Spot/USDT + Perp USDⓈ-M compatibles
sur Binance, avec filtres de liquidité et gestion des contrats à multiplicateur.

Usage:
    python -m v7.core.carry_scanner              # affiche la liste
    python -m v7.core.carry_scanner --save       # met à jour carry_assets.yaml
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("v7.core.carry_scanner")

# ── Seuils de liquidité ──
MIN_SPOT_VOLUME_24H_USD = 5_000_000    # $5M volume spot minimum
MIN_PERP_VOLUME_24H_USD = 10_000_000   # $10M volume perp minimum
MIN_OPEN_INTEREST_USD    = 2_000_000   # $2M open interest minimum
MAX_SPREAD_BPS           = 15           # spread max 0.15%
MIN_FUNDING_HISTORY_DAYS = 90           # au moins 90j d'historique de funding

# ── Actifs exclus (stablecoins, wrapped, tokens problématiques) ──
EXCLUDED_BASES = {
    "USDC", "USDT", "DAI", "TUSD", "BUSD", "USDP", "FDUSD",  # stablecoins
    "WBTC", "WETH", "WBETH",  # wrapped (suivre l'original)
    "USTC", "LUNC",  # effondrés
}

# ── Multiplier contracts ──
# Binance utilise des symboles comme 1000PEPEUSDT, 1000SHIBUSDT, etc.
# Le champ contractSize donne la taille réelle du contrat.
MULTIPLIER_PREFIXES = [
    ("1000000", 1_000_000.0),
    ("1000",    1_000.0),
    ("100",     100.0),
]


def _resolve_spot_underlying(futures_base: str, spot_bases: set[str]) -> tuple[str | None, float]:
    """Résout le sous-jacent spot pour un contrat perp (ex: 1000PEPE → PEPE, ×1000)."""
    if futures_base in spot_bases:
        return futures_base, 1.0

    for prefix, multiplier in MULTIPLIER_PREFIXES:
        if futures_base.startswith(prefix):
            candidate = futures_base[len(prefix):]
            if candidate in spot_bases:
                return candidate, multiplier

    return None, 0.0


def scan_carry_universe(*, save: bool = False, min_spot_vol: float = MIN_SPOT_VOLUME_24H_USD,
                         min_perp_vol: float = MIN_PERP_VOLUME_24H_USD,
                         min_oi: float = MIN_OPEN_INTEREST_USD,
                         max_spread_bps: int = MAX_SPREAD_BPS) -> list[dict[str, Any]]:
    """
    Scanne Binance pour trouver tous les couples Spot/USDT ∩ Perp USDⓈ-M éligibles.

    Returns:
        Liste de dicts avec: symbol, spot_symbol, perp_symbol, multiplier,
        contract_size, spot_volume_24h, perp_volume_24h, open_interest, spread_bps.
    """
    try:
        import ccxt
    except ImportError:
        logger.error("CCXT non installé. pip install ccxt")
        return []

    spot_ex = ccxt.binance({"enableRateLimit": True})
    perp_ex = ccxt.binanceusdm({"enableRateLimit": True})

    # ── 1. Charger la structure des marchés (exchangeInfo) ──
    logger.info("Chargement des marchés Spot...")
    try:
        spot_markets = spot_ex.load_markets()
    except Exception as e:
        logger.error("Échec chargement marchés Spot: %s", e)
        return []

    logger.info("Chargement des marchés Perp USDⓈ-M...")
    try:
        perp_markets = perp_ex.load_markets()
    except Exception as e:
        logger.error("Échec chargement marchés Perp: %s", e)
        return []

    # Indexer les marchés spot USDT actifs
    spot_usdt: dict[str, dict] = {}
    for market in spot_markets.values():
        if (market.get("spot") and market.get("active")
                and market.get("quote") == "USDT"):
            spot_usdt[market["base"]] = market

    logger.info("Spot USDT actifs: %d paires", len(spot_usdt))
    spot_bases = set(spot_usdt.keys())

    # ── 2. Intersection Spot ∩ Perp (sans volumes) ──
    candidates: list[dict[str, Any]] = []
    for market in perp_markets.values():
        if not (market.get("swap") and market.get("active")
                and market.get("quote") == "USDT"
                and market.get("settle") == "USDT"
                and market.get("linear")):
            continue

        futures_base = market["base"]
        spot_base, multiplier = _resolve_spot_underlying(futures_base, spot_bases)
        if spot_base is None:
            continue
        if spot_base.upper() in EXCLUDED_BASES:
            continue

        contract_size = market.get("contractSize", 1.0) or 1.0
        candidates.append({
            "symbol": f"{spot_base}/USDT",
            "spot_symbol": spot_usdt[spot_base]["symbol"],
            "perp_symbol": market["symbol"],
            "multiplier": multiplier,
            "contract_size": float(contract_size),
            "perp_id": market.get("id", ""),
            "spot_base": spot_base,
        })

    logger.info("Candidats Spot∩Perp (avant filtres volume): %d", len(candidates))
    if not candidates:
        return []

    # ── 3. Récupérer les volumes/ spreads via fetch_tickers ──
    spot_symbols = [c["spot_symbol"] for c in candidates]
    perp_symbols = [c["perp_symbol"] for c in candidates]

    spot_tickers: dict[str, dict] = {}
    perp_tickers: dict[str, dict] = {}

    logger.info("Récupération des tickers spot (%d symboles)...", len(spot_symbols))
    try:
        # Binance limite ~100 symboles par appel, on découpe
        for i in range(0, len(spot_symbols), 80):
            chunk = spot_symbols[i:i+80]
            tickers = spot_ex.fetch_tickers(chunk)
            spot_tickers.update(tickers)
    except Exception as e:
        logger.warning("Échec tickers spot: %s — on continue sans filtre volume", e)

    logger.info("Récupération des tickers perp (%d symboles)...", len(perp_symbols))
    try:
        for i in range(0, len(perp_symbols), 80):
            chunk = perp_symbols[i:i+80]
            tickers = perp_ex.fetch_tickers(chunk)
            perp_tickers.update(tickers)
    except Exception as e:
        logger.warning("Échec tickers perp: %s — on continue sans filtre volume", e)

    # ── 4. Appliquer les filtres ──
    results: list[dict[str, Any]] = []
    for c in candidates:
        spot_t = spot_tickers.get(c["spot_symbol"], {})
        perp_t = perp_tickers.get(c["perp_symbol"], {})

        spot_vol = spot_t.get("quoteVolume") or spot_t.get("quote_volume") or 0
        perp_vol = perp_t.get("quoteVolume") or perp_t.get("quote_volume") or 0
        # OI: Binance USDⓈ-M ticker → info.openInterest (string), CCXT ≥4.4 → openInterest (float)
        oi_raw = (perp_t.get("info", {}).get("openInterest")
                  or perp_t.get("openInterest")
                  or perp_t.get("openInterestValue")
                  or 0)

        try:
            spot_vol_24h = float(spot_vol) if spot_vol else 0.0
        except (ValueError, TypeError):
            spot_vol_24h = 0.0
        try:
            perp_vol_24h = float(perp_vol) if perp_vol else 0.0
        except (ValueError, TypeError):
            perp_vol_24h = 0.0
        try:
            open_interest = float(oi_raw) if oi_raw else 0.0
        except (ValueError, TypeError):
            open_interest = 0.0

        # Si pas de données ticker (API down), on inclut quand même
        if spot_t and spot_vol_24h < min_spot_vol:
            continue
        if perp_t and perp_vol_24h < min_perp_vol:
            continue
        if perp_t and open_interest > 0 and open_interest < min_oi:
            continue

        results.append({
            "symbol": c["symbol"],
            "spot_symbol": c["spot_symbol"],
            "perp_symbol": c["perp_symbol"],
            "multiplier": c["multiplier"],
            "contract_size": c["contract_size"],
            "spot_volume_24h_usd": spot_vol_24h,
            "perp_volume_24h_usd": perp_vol_24h,
            "open_interest_usd": open_interest,
            "perp_id": c["perp_id"],
        })

    # Trier par volume spot décroissant
    results.sort(key=lambda r: r["spot_volume_24h_usd"], reverse=True)

    logger.info("Univers carry éligible: %d actifs (filtré depuis %d candidats)",
                len(results), len(candidates))

    if save:
        _update_carry_config(results, optimize=optimize)

    return results


def compute_optimized_params(assets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """
    Calcule les paramètres optimisés pour chaque actif à partir des données réelles.
    
    Retourne un dict {symbol: {_optimized_capital, _optimized_stress_loss_pct, ...}}
    qui sera stocké dans carry_assets.yaml sans écraser les valeurs actuelles.
    """
    try:
        import ccxt
        import numpy as np
    except ImportError:
        logger.warning("CCXT ou numpy non disponible — optimisation ignorée")
        return {}

    perp_ex = ccxt.binanceusdm({"enableRateLimit": True})
    optimized: dict[str, dict[str, Any]] = {}

    total_spot_vol = sum(a.get("spot_volume_24h_usd", 0) for a in assets) or 1
    total_oi = sum(a.get("open_interest_usd", 0) for a in assets) or 1

    for i, asset in enumerate(assets):
        sym = asset["symbol"]
        perp_sym = asset["perp_symbol"]
        logger.info("Optimisation %s (%d/%d)...", sym, i + 1, len(assets))

        opt: dict[str, Any] = {}

        # ── 1. Capital proportionnel au volume spot ──
        spot_vol = asset.get("spot_volume_24h_usd", 0)
        vol_share = spot_vol / total_spot_vol if total_spot_vol > 0 else 1.0 / len(assets)
        opt["_optimized_capital"] = max(500, min(5000, int(14000 * vol_share)))

        # ── 2. Stress loss basé sur la volatilité 30j ──
        try:
            ohlcv = perp_ex.fetch_ohlcv(perp_sym, "1d", limit=30)
            if ohlcv and len(ohlcv) >= 7:
                closes = [c[4] for c in ohlcv if c[4] is not None]
                if len(closes) >= 7:
                    returns = np.diff(np.log(closes))
                    vol_30d = float(np.std(returns) * np.sqrt(365) * 100)  # volatilité annualisée %
                    opt["_optimized_stress_loss_pct"] = round(max(0.03, min(0.25, vol_30d / 100)), 2)
                    opt["_optimized_volatility_30d_pct"] = round(vol_30d, 1)
        except Exception as e:
            logger.debug("Volatilité %s: %s", sym, e)

        # ── 3. Min funding basé sur l'historique ──
        try:
            funding_rates = perp_ex.fetch_funding_rate_history(perp_sym, limit=90)
            if funding_rates and len(funding_rates) >= 10:
                rates = [f["fundingRate"] for f in funding_rates if f.get("fundingRate") is not None]
                rates = [float(r) for r in rates]
                if rates:
                    pct_positive = sum(1 for r in rates if r > 0) / len(rates)
                    opt["_optimized_min_funding"] = round(max(0.00001, min(0.005, 
                        float(np.median([r for r in rates if r > 0]) or 0.0001) * 0.5)), 5)
                    opt["_optimized_funding_positive_pct"] = round(pct_positive * 100, 1)
                    opt["_optimized_funding_samples"] = len(rates)
        except Exception as e:
            logger.debug("Funding %s: %s", sym, e)

        # ── 4. Safety cap basé sur l'open interest ──
        oi = asset.get("open_interest_usd", 0)
        oi_share = oi / total_oi if total_oi > 0 else 1.0 / len(assets)
        opt["_optimized_safety_cap"] = max(50, min(500, int(opt.get("_optimized_capital", 2000) * max(0.05, oi_share))))

        # ── 5. Max hold days basé sur la persistance du funding ──
        try:
            if funding_rates and len(funding_rates) >= 30:
                # Compter les séquences consécutives de funding positif
                signs = [1 if float(f["fundingRate"]) > 0 else 0 for f in funding_rates]
                max_streak = 0
                current_streak = 0
                for s in signs:
                    if s == 1:
                        current_streak += 1
                        max_streak = max(max_streak, current_streak)
                    else:
                        current_streak = 0
                opt["_optimized_max_hold_days"] = max(7, min(30, max_streak * 8 // 24))  # 8h intervals → days
                opt["_optimized_funding_max_streak"] = max_streak
        except Exception:
            pass

        optimized[sym] = opt
        # Flag de viabilité
        opt["_optimized_viable"] = (
            opt.get("_optimized_funding_positive_pct", 0) > 0 and
            opt.get("_optimized_stress_loss_pct", 0) < 0.30 and
            opt.get("_optimized_volatility_30d_pct", 999) < 200
        )

    logger.info("Optimisation terminée pour %d actifs", len(optimized))
    return optimized


def _update_carry_config(assets: list[dict[str, Any]], optimize: bool = False) -> None:
    """Met à jour carry_assets.yaml avec les actifs scannés (préserve les params existants)."""
    config_path = Path(__file__).resolve().parent.parent.parent / "config" / "carry_assets.yaml"
    # Priorité runtime writable
    data_path = Path("/app/data") / "carry_assets.yaml"
    if data_path.exists():
        config_path = data_path

    # Charger la config existante
    existing: dict = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            existing = yaml.safe_load(f) or {}

    existing_assets = existing.get("assets", {})
    global_cfg = existing.get("global", {})

    # Calculer les paramètres optimisés si demandé
    optimized_params: dict = {}
    if optimize:
        logger.info("Calcul des paramètres optimisés...")
        optimized_params = compute_optimized_params(assets)

    # Fusion : nouveaux actifs ajoutés avec defaults, existants préservés
    new_assets: dict = {}
    # Niveau 1 (top 15 par volume) → capital standard
    tier1_capital = 2000
    # Niveau 2 (16-30) → capital réduit
    tier2_capital = 1000
    # Niveau 3 (meme coins, 31+) → capital minimal
    tier3_capital = 500

    meme_coins = {"SHIB", "PEPE", "FLOKI", "BONK", "WIF", "TURBO", "NEIRO"}

    for i, asset in enumerate(assets):
        sym = asset["symbol"]
        base = sym.split("/")[0]

        # Préserver les params existants si déjà configurés
        if sym in existing_assets:
            new_assets[sym] = existing_assets[sym]
            continue

        # Déterminer le tier
        if base in meme_coins or i >= 30:
            capital = tier3_capital
            fraction = 0.30
        elif i >= 15:
            capital = tier2_capital
            fraction = 0.40
        else:
            capital = tier1_capital
            fraction = 0.50

        new_assets[sym] = {
            "enabled": i < 15 and spot_vol > 0 and perp_vol > 0,  # top 15 avec liquidité
            "capital": capital,
            "fraction": fraction,
            "safety_cap": int(capital * 0.10),
            "stress_loss_pct": 0.10,
            "max_hold_days": 14,
            "min_funding": 0.00005,
            "max_funding": 0.003,
            "exit_after_hours": 72,
            "leverage": 1.0,
            "icon_url": "",  # à remplir manuellement avec le logo officiel
            "_scanner_spot_vol_24h": asset["spot_volume_24h_usd"],
            "_scanner_perp_vol_24h": asset["perp_volume_24h_usd"],
            "_scanner_oi": asset["open_interest_usd"],
            "_scanner_multiplier": asset["multiplier"],
            "_scanner_contract_size": asset["contract_size"],
            "_scanner_last_scan": None,
        }
        # Fusionner les params optimisés (ne modifie pas les valeurs actuelles)
        if sym in optimized_params:
            new_assets[sym].update(optimized_params[sym])

    cfg = {
        "global": global_cfg,
        "assets": new_assets,
        "_scanner_meta": {
            "total_spot_pairs": len(assets),
            "total_eligible": len(assets),
            "filters": {
                "min_spot_volume_24h_usd": MIN_SPOT_VOLUME_24H_USD,
                "min_perp_volume_24h_usd": MIN_PERP_VOLUME_24H_USD,
                "min_open_interest_usd": MIN_OPEN_INTEREST_USD,
                "max_spread_bps": MAX_SPREAD_BPS,
            },
        },
    }

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    logger.info("carry_assets.yaml mis à jour: %d actifs", len(new_assets))


# ── CLI ──
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    save_flag = "--save" in sys.argv
    optimize_flag = "--optimize" in sys.argv

    universe = scan_carry_universe(save=save_flag, optimize=optimize_flag)

    # Affichage
    print(f"\n{'='*80}")
    print(f"Univers Funding Carry — {len(universe)} actifs éligibles")
    print(f"{'='*80}")
    print(f"{'Actif':<12} {'Spot Vol 24h':>14} {'Perp Vol 24h':>14} {'OI':>12} {'Multiplier':>10}")
    print(f"{'-'*12} {'-'*14} {'-'*14} {'-'*12} {'-'*10}")
    for a in universe:
        print(f"{a['symbol']:<12} ${a['spot_volume_24h_usd']:>13,.0f} "
              f"${a['perp_volume_24h_usd']:>13,.0f} "
              f"${a['open_interest_usd']:>11,.0f} "
              f"{a['multiplier']:>10.0f}")
    print(f"{'='*80}")

    if save_flag:
        print("\n✅ carry_assets.yaml mis à jour.")
    else:
        print("\n💡 Utilise --save pour mettre à jour carry_assets.yaml.")
