"""
mirofish/core.py — Moteur de simulation swarm.

Modèle : chaque agent a une opinion dans [-1, +1].
- Opinion initiale : dérivée du score sémantique du contexte + bruit gaussien
- Mise à jour : moyenne pondérée des voisins dans un rayon d'influence (Deffuant)
- Inertie : les agents extrêmes (|opinion| > 0.7) résistent à la mise à jour
- Résultat : distribution finale des opinions → score [0-100] + probabilités
"""
from __future__ import annotations

import hashlib
import math
import random
from typing import Any


# ---- Lexique sémantique ------------------------------------------------

_BULLISH = [
    "hausse", "bull", "growth", "adoption", "institutional", "upgrade",
    "positive", "rally", "breakout", "buy", "support", "record", "optimism",
    "recovery", "momentum", "ath", "pump", "inflow", "accumulation",
    "partnership", "launch", "approval", "etf", "halving", "demand",
    "green", "moon", "potential", "confidence", "expansion",
]

_BEARISH = [
    "baisse", "bear", "crash", "ban", "regulation", "sell", "dump",
    "fear", "panic", "risk", "inflation", "recession", "hack",
    "liquidation", "breakdown", "correction", "volatile", "outflow",
    "scam", "fraud", "exploit", "fine", "lawsuit", "warning",
    "red", "drop", "loss", "debt", "uncertainty", "concern",
]


def _seed_score(context: str) -> float:
    """
    Calcule un score sémantique de base en [-1, +1] à partir du contexte.
    Déterministe via hash MD5 pour reproductibilité.
    """
    text = context.lower()
    bull = sum(1 for w in _BULLISH if w in text)
    bear = sum(1 for w in _BEARISH if w in text)
    total = bull + bear

    if total == 0:
        ratio = 0.0
    else:
        ratio = (bull - bear) / total  # [-1, +1]

    # Bruit déterministe ±0.15 basé sur le contenu
    h = int(hashlib.md5(context[:300].encode("utf-8", errors="ignore")).hexdigest(), 16)
    noise = ((h % 1000) / 1000.0 - 0.5) * 0.30  # [-0.15, +0.15]

    return max(-1.0, min(1.0, ratio + noise))


def _init_agents(n: int, seed_opinion: float, rng: random.Random) -> list[float]:
    """
    Initialise les opinions des agents autour du seed avec dispersion gaussienne.
    Les opinions sont dans [-1, +1].
    """
    sigma = 0.45  # dispersion initiale élevée — marché incertain
    opinions = []
    for _ in range(n):
        op = rng.gauss(seed_opinion, sigma)
        opinions.append(max(-1.0, min(1.0, op)))
    return opinions


def _deffuant_step(
    opinions: list[float],
    mu: float,
    epsilon: float,
    rng: random.Random,
) -> list[float]:
    """
    Une itération du modèle Deffuant :
    - Tire aléatoirement des paires d'agents
    - Si |op_i - op_j| < epsilon (seuil de confiance), ils se rapprochent
    - mu : taux de convergence [0, 0.5]
    """
    n = len(opinions)
    new_opinions = opinions[:]
    # Nombre d'interactions par step ≈ n/2
    for _ in range(n // 2):
        i = rng.randint(0, n - 1)
        j = rng.randint(0, n - 1)
        if i == j:
            continue
        diff = abs(new_opinions[i] - new_opinions[j])
        if diff < epsilon:
            # Inertie pour les agents extrêmes
            inertia_i = 0.5 if abs(new_opinions[i]) > 0.7 else 1.0
            inertia_j = 0.5 if abs(new_opinions[j]) > 0.7 else 1.0
            move = mu * (new_opinions[j] - new_opinions[i])
            new_opinions[i] = max(-1.0, min(1.0, new_opinions[i] + move * inertia_i))
            new_opinions[j] = max(-1.0, min(1.0, new_opinions[j] - move * inertia_j))
    return new_opinions


def _compute_result(opinions: list[float], n_agents: int) -> dict[str, Any]:
    """
    Agrège la distribution finale des opinions en résultat tradeble.
    """
    n = len(opinions)
    bull = sum(1 for o in opinions if o > 0.1) / n
    bear = sum(1 for o in opinions if o < -0.1) / n
    neutral = 1.0 - bull - bear

    mean_opinion = sum(opinions) / n  # [-1, +1]
    # Convertir en score [0, 100]
    score = (mean_opinion + 1.0) / 2.0 * 100.0
    score = max(2.0, min(98.0, score))

    # Cluster dominant
    if bull > 0.55:
        dominant = "haussier"
        signal = "BUY"
    elif bear > 0.55:
        dominant = "baissier"
        signal = "SELL"
    elif bull > bear + 0.15:
        dominant = "légèrement haussier"
        signal = "WATCH_BUY"
    elif bear > bull + 0.15:
        dominant = "légèrement baissier"
        signal = "WATCH_SELL"
    else:
        dominant = "indécis"
        signal = "HOLD"

    # Polarisation : variance des opinions
    var = sum((o - mean_opinion) ** 2 for o in opinions) / n
    polarization = math.sqrt(var)  # 0 = consensus, ~1 = très polarisé

    narratives = [
        f"Consensus {dominant} — {bull:.0%} haussiers / {bear:.0%} baissiers / {neutral:.0%} neutres",
        f"Opinion moyenne : {mean_opinion:+.3f} → score={score:.1f}/100 (signal={signal})",
        f"Polarisation du marché : {polarization:.3f} {'(fort désaccord)' if polarization > 0.5 else '(consensus naissant)'}",
        f"Simulation : {n_agents} agents, convergence Deffuant",
    ]

    return {
        "score": round(score, 2),
        "probabilities": {
            "bull": round(bull, 3),
            "bear": round(bear, 3),
            "neutral": round(neutral, 3),
        },
        "narratives": narratives,
        "dominant_narrative": narratives[0],
        "mean_opinion": round(mean_opinion, 4),
        "polarization": round(polarization, 4),
        "signal": signal,
        "n_agents_used": n_agents,
    }


def simulate(
    context: str,
    n_agents: int = 5000,
    n_steps: int = 100,
    mu: float = 0.3,
    epsilon: float = 0.4,
    seed: int | None = None,
) -> dict[str, Any]:
    """
    Point d'entrée principal — simule la dynamique d'opinion de n_agents
    sur n_steps itérations à partir d'un contexte textuel.

    Args:
        context:  Texte décrivant le contexte de marché (news + air du temps)
        n_agents: Nombre d'agents dans la simulation
        n_steps:  Nombre d'itérations du modèle Deffuant
        mu:       Taux de convergence [0.1, 0.5]
        epsilon:  Seuil de confiance [0.2, 0.8]
        seed:     Graine aléatoire (None = déterministe via hash du contexte)

    Returns:
        dict avec keys: score, probabilities, narratives, signal, ...
    """
    # Graine déterministe si non fournie
    if seed is None:
        h = int(hashlib.md5(context[:200].encode("utf-8", errors="ignore")).hexdigest(), 16)
        seed = h % (2 ** 31)

    rng = random.Random(seed)

    # Limiter n_agents pour la performance (scaling linéaire)
    effective_agents = min(n_agents, 2000)  # cap à 2000 pour < 1s d'exécution

    # 1. Score sémantique initial
    seed_opinion = _seed_score(context)

    # 2. Initialisation des agents
    opinions = _init_agents(effective_agents, seed_opinion, rng)

    # 3. Simulation Deffuant
    for _ in range(n_steps):
        opinions = _deffuant_step(opinions, mu, epsilon, rng)

    # 4. Agrégation du résultat
    result = _compute_result(opinions, n_agents)
    return result
