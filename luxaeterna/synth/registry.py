"""Lux Aeterna — instrument-type registry (name -> factory)."""

from __future__ import annotations

_REGISTRY: dict = {}


def register(name: str, factory) -> None:
    _REGISTRY[name] = factory


def build(name: str, **params):
    if name not in _REGISTRY:
        raise KeyError(f"unknown instrument type {name!r}")
    return _REGISTRY[name](**params)
