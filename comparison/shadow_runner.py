"""
comparison/shadow_runner.py — Shadow Profile Evaluator

Après chaque cycle, évalue ce qu'auraient fait les profils shadow
avec les mêmes données de marché (scores bruts identiques).

Seul le scoring pondéré + la logique de décision/risque diffèrent.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml

logger = logging.getLogger("zeitgeist.shadow")

_PROFILES_PATH = Path(__file__).resolve().parent.parent / "config" / "profiles.yaml"


def load_profiles() -> dict[str, dict]:
    """Charge les profils depuis config/profiles.yaml."""
    if not _PROFILES_PATH.exists():
        logger.warning(f"Profils introuvables : {_PROFILES_PATH}")
        return {}
    with open(_PROFILES_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("profiles", {})


def evaluate_shadow_profiles(
    cycle_id: str,
    asset: str,
    timestamp: str,
    mirofish_score: float,
    market_score: float,
    agent_scores: dict[str, float],
    contrarian_score: float,
    market_indicators: dict | None,
) -> list[dict]:
    """
    Évalue tous les profils shadow avec les mêmes scores bruts.
    Le profil actif est ignoré (géré par le pipeline principal).

    Returns:
        Liste de dicts {profile, action, score, position_size_usd}
    """
    from storage.database import log_shadow_decision

    profiles = load_profiles()
    results = []

    for name, cfg in profiles.items():
        if cfg.get("active", False):
            continue  # profil actif → déjà traité par le pipeline normal

        try:
            decision = _evaluate_single(
                profile_name=name,
                profile_cfg=cfg,
                mirofish_score=mirofish_score,
                market_score=market_score,
                agent_scores=agent_scores,
                contrarian_score=contrarian_score,
                market_indicators=market_indicators,
            )

            log_shadow_decision(
                cycle_id=cycle_id,
                profile_name=name,
                timestamp=timestamp,
                asset=asset,
                decision=decision,
                config_snapshot=json.dumps(
                    {"scoring": cfg.get("scoring", {}), "risk": cfg.get("risk", {})},
                    ensure_ascii=False,
                ),
            )

            result = {
                "profile": name,
                "label": cfg.get("label", name),
                "action": decision["action"],
                "score": decision["score"],
                "position_size_usd": decision.get("position_size_usd", 0),
            }
            results.append(result)

            logger.info(
                f"Shadow [{name}]: {decision['action']} "
                f"score={decision['score']:.1f} size=${decision.get('position_size_usd', 0):.0f}"
            )

        except Exception as exc:
            logger.warning(f"Shadow [{name}] erreur : {exc}")

    return results


# ──────────────────────────────────────────────────────────────
# Évaluation d'un seul profil (scoring + décision interne)
# ──────────────────────────────────────────────────────────────

def _evaluate_single(
    profile_name: str,
    profile_cfg: dict,
    mirofish_score: float,
    market_score: float,
    agent_scores: dict[str, float],
    contrarian_score: float,
    market_indicators: dict | None,
) -> dict:
    """Calcule score pondéré + décision pour un profil shadow donné."""
    scoring_cfg = profile_cfg.get("scoring", {})
    risk_cfg = profile_cfg.get("risk", {})

    # ── Score pondéré ──
    w_mf = scoring_cfg.get("mirofish", 0.15)
    w_mkt = scoring_cfg.get("market", 0.45)
    w_agt = scoring_cfg.get("agents", 0.25)
    w_ctr = scoring_cfg.get("contrarian", 0.15)

    agents_mean = (
        sum(agent_scores.values()) / len(agent_scores)
        if agent_scores else 50.0
    )

    global_score = (
        mirofish_score * w_mf
        + market_score * w_mkt
        + agents_mean * w_agt
        + contrarian_score * w_ctr
    )
    global_score = round(max(0.0, min(100.0, global_score)), 2)

    # ── Paramètres de risque ──
    buy_threshold = risk_cfg.get("buy_threshold", 68)
    exit_threshold = risk_cfg.get("exit_threshold", 52)
    mode = risk_cfg.get("mode", "balanced")
    pos_size_pct = risk_cfg.get("position_size_pct", 5.0)
    atr_sl = risk_cfg.get("atr_multiplier_sl", 2.0)
    atr_tp = risk_cfg.get("atr_multiplier_tp", 3.0)
    ma50_mode = risk_cfg.get("ma50_filter_mode", "gradual")
    ma50_strong = risk_cfg.get("ma50_strong_signal_threshold", 72)
    ma50_size_fac = risk_cfg.get("ma50_gradual_size_factor", 0.5)
    max_pos = risk_cfg.get("max_open_positions", 3)
    capital = 10_000.0  # capital standard pour comparaison équitable

    mode_mult = {"conservative": 0.5, "balanced": 1.0, "aggressive": 1.5}.get(mode, 1.0)
    kelly_max = 0.25 * mode_mult
    pos_size_pct *= mode_mult

    # ── Positions shadow ouvertes ──
    from storage.database import get_shadow_open_positions_for_profile

    open_buys = [
        p for p in get_shadow_open_positions_for_profile(profile_name)
        if p["action"] == "BUY"
    ]
    has_long = len(open_buys) > 0

    price = (market_indicators or {}).get("price", 0.0)
    atr = (market_indicators or {}).get("atr_14", price * 0.02)
    above_ma50 = (market_indicators or {}).get("above_ma50", True)
    ma_50 = (market_indicators or {}).get("ma_50", 0.0)

    # ── Logique position-aware ──
    if has_long:
        if global_score < exit_threshold:
            action = "SELL"
            # Clôture de la position la plus ancienne
            from storage.database import close_shadow_position
            close_shadow_position(open_buys[0]["id"], price)
        else:
            action = "HOLD"
    else:
        action = "BUY" if global_score >= buy_threshold else "HOLD"

    # Max positions
    if action == "BUY" and max_pos > 0 and len(open_buys) >= max_pos:
        action = "HOLD"

    # Filtre MA50
    ma50_penalty = 1.0
    if action == "BUY" and not above_ma50 and ma_50 > 0:
        if ma50_mode == "block":
            action = "HOLD"
        elif ma50_mode == "gradual":
            if global_score < ma50_strong:
                action = "HOLD"
            else:
                ma50_penalty = ma50_size_fac

    # ── Sizing & SL/TP ──
    position_size = 0.0
    sl_price = tp_price = price

    if action in ("BUY", "SELL") and action != "SELL":
        # Sizing uniquement pour BUY (SELL clôture une position existante)
        win_rate, rr = 0.55, 1.5
        kelly = max(0.0, min((win_rate * rr - (1 - win_rate)) / rr, kelly_max))
        max_size = capital * (pos_size_pct / 100)
        base_size = min(capital * kelly, max_size)
        conviction = abs(global_score - 50.0) / 50.0
        conviction_mult = max(0.3, min(1.0, 0.3 + 0.7 * conviction))
        position_size = round(base_size * conviction_mult * ma50_penalty, 2)

        atr = max(atr, price * 0.001)
        sl_price = round(price - atr * atr_sl, 2)
        tp_price = round(price + atr * atr_tp, 2)

    return {
        "action": action,
        "score": global_score,
        "position_size_usd": position_size,
        "entry_price": price,
        "sl_price": sl_price,
        "tp_price": tp_price,
    }


# ──────────────────────────────────────────────────────────────
# Post-mortem shadow : évalue P&L 24h après
# ──────────────────────────────────────────────────────────────

def evaluate_shadow_postmortems() -> int:
    """
    Évalue le P&L des shadow positions ouvertes depuis > 24h.
    Appelé depuis _run_post_mortem_if_needed() dans main.py.

    Returns:
        Nombre de positions évaluées.
    """
    from storage.database import (
        get_shadow_pending_postmortems,
        update_shadow_result,
    )

    try:
        pending = get_shadow_pending_postmortems()
        if not pending:
            return 0

        # Récupérer le prix actuel une seule fois
        from agents.market_data_agent import MarketDataAgent

        agent = MarketDataAgent()
        price = agent.get_indicators("BTC/USDT").get("price", 0)
        if not price:
            return 0

        evaluated = 0
        for shadow in pending:
            shadow_action = shadow["action"]
            entry = float(shadow.get("entry_price") or 0)
            size = float(shadow.get("position_size") or 0)

            if shadow_action == "HOLD" or entry <= 0 or size <= 0:
                update_shadow_result(shadow["id"], 0.0)
                evaluated += 1
                continue

            qty = size / entry
            sl = float(shadow.get("sl_price") or 0)
            tp = float(shadow.get("tp_price") or 0)

            # Vérifier SL/TP
            if shadow_action == "BUY":
                if sl and price <= sl:
                    pnl = (sl - entry) * qty
                elif tp and price >= tp:
                    pnl = (tp - entry) * qty
                else:
                    pnl = (price - entry) * qty
            else:
                pnl = (entry - price) * qty

            update_shadow_result(shadow["id"], round(pnl, 2))
            evaluated += 1

        if evaluated:
            logger.info(f"Shadow post-mortem : {evaluated} positions évaluées")
        return evaluated

    except Exception as exc:
        logger.warning(f"Shadow post-mortem erreur : {exc}")
        return 0
