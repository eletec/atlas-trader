"""
v4/core/context_store.py — Mémoire partagée entre toutes les lanes d'un canvas.

Le ContextStore est un dict clé/valeur thread-safe.
Chaque nœud écrit ses outputs à la fin de son exécution.
Les nœuds asynchrones (Lane 2, Lane 3...) publient leurs valeurs ici.
Les nœuds synchrones (Lane 1) lisent la dernière valeur disponible au moment de décider.

Un slot absent ou trop ancien retourne sa valeur fallback sans exception.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContextSlot:
    value: Any
    updated_at: float = field(default_factory=time.time)
    source_node: str = ""

    @property
    def age_s(self) -> float:
        return time.time() - self.updated_at

    def is_stale(self, max_age_s: float) -> bool:
        return self.age_s > max_age_s


class ContextStore:
    """
    Mémoire partagée entre toutes les lanes d'un canvas (un store par asset).

    Usage :
        store = ContextStore(asset="BTC/USDT")
        store.set("btc_temperature", -42.0, source="temperature_1")
        value = store.get("btc_temperature", fallback=0.0, max_age_s=1800)
        snapshot = store.snapshot()
    """

    def __init__(self, asset: str = "") -> None:
        self.asset = asset
        self._slots: dict[str, ContextSlot] = {}
        self._lock = threading.Lock()

    def set(self, key: str, value: Any, source: str = "") -> None:
        with self._lock:
            self._slots[key] = ContextSlot(
                value=value,
                updated_at=time.time(),
                source_node=source,
            )

    def get(
        self,
        key: str,
        fallback: Any = None,
        max_age_s: float | None = None,
    ) -> Any:
        with self._lock:
            slot = self._slots.get(key)
        if slot is None:
            return fallback
        if max_age_s is not None and slot.is_stale(max_age_s):
            return fallback
        return slot.value

    def get_slot(self, key: str) -> ContextSlot | None:
        with self._lock:
            return self._slots.get(key)

    def snapshot(self) -> dict[str, dict]:
        """Retourne un snapshot lisible de tous les slots (pour le dashboard)."""
        with self._lock:
            return {
                key: {
                    "value": slot.value,
                    "age_s": round(slot.age_s, 1),
                    "source": slot.source_node,
                    "updated_at": slot.updated_at,
                }
                for key, slot in self._slots.items()
            }

    def clear(self) -> None:
        with self._lock:
            self._slots.clear()


## Global registry: one store per asset + a global store for cross-cutting lanes
class ContextRegistry:
    """
    Registre singleton de tous les ContextStore actifs.
    Accès : ContextRegistry.get_store("BTC/USDT") ou ContextRegistry.global_store()
    """
    _stores: dict[str, ContextStore] = {}
    _lock = threading.Lock()

    @classmethod
    def get_store(cls, asset: str) -> ContextStore:
        with cls._lock:
            if asset not in cls._stores:
                cls._stores[asset] = ContextStore(asset=asset)
            return cls._stores[asset]

    @classmethod
    def global_store(cls) -> ContextStore:
        """Store partagé pour les lanes transverses (FearGreed, Macro, CorrelMonitor...)."""
        return cls.get_store("__global__")

    @classmethod
    def all_snapshots(cls) -> dict[str, dict]:
        with cls._lock:
            return {asset: store.snapshot() for asset, store in cls._stores.items()}
