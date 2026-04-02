"""
mirofish — Simulation swarm locale pour Atlas Trader.
Implémente une simulation multi-agents inspirée des modèles de marché basés
sur des automates cellulaires et la propagation d'opinion (Deffuant/Hegselmann).

API compatible avec l'interface attendue par mirofish_wrapper.py :
    result = mirofish.simulate(context, n_agents, n_steps)
"""
from __future__ import annotations

from mirofish.core import simulate

__version__ = "1.0.0-local"
__all__ = ["simulate"]
