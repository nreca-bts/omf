"""Stable public business API."""

from __future__ import annotations

from .hc import evaluate_hosting_capacity_impl
from .upgrade import plan_upgrade_impl


def evaluate_hosting_capacity(site_id: str) -> dict:
    """Evaluate maximum simulation-free hosting capacity for one frozen Iowa240 site."""
    return evaluate_hosting_capacity_impl(site_id)


def plan_upgrade(site_id: str, target_hc_mw: float, catalog_id: str = "default") -> dict:
    """Plan catalog equipment actions to reach an absolute HC target."""
    return plan_upgrade_impl(site_id, target_hc_mw, catalog_id)
