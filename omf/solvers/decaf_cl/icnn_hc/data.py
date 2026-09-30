"""Safe package-relative loading and validation of frozen runtime data."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any

import numpy as np


class RuntimeDataError(RuntimeError):
    """Raised when the frozen runtime data is missing or internally misaligned."""


def _insert(tree: dict[str, Any], key: str, value: np.ndarray) -> None:
    parts = key.split("__")
    cursor = tree
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[parts[-1]] = value


def _validate(data: dict[str, Any]) -> None:
    required = ["sites", "critical", "models", "thermal", "regulator", "candidate", "catalogs", "config", "outputs"]
    missing = [name for name in required if name not in data]
    if missing:
        raise RuntimeDataError(f"Missing runtime data groups: {missing}")
    n_sites = len(data["sites"]["id"])
    n_hours = len(data["critical"]["hours"])
    n_outputs = len(data["outputs"]["name"])
    if data["critical"]["base_features"].shape[0] != n_hours:
        raise RuntimeDataError("Critical-hour feature matrix is not aligned with critical hours")
    if data["sites"]["direction"].shape[0] != n_sites:
        raise RuntimeDataError("Site direction matrix is not aligned with site IDs")
    if data["thermal"]["gamma_frac_per_mw"].shape[:2] != (n_sites, n_hours):
        raise RuntimeDataError("Thermal sensitivity tensor is not aligned with sites/hours")
    response = data["regulator"]["response_margin_pu"]
    if response.shape[2:] != (n_hours, n_outputs):
        raise RuntimeDataError("Regulator response library is not aligned with hours/ICNN outputs")
    if "candidate" in data:
        candidate = data["candidate"]
        count = len(candidate["locations"])
        if candidate["available_phases"].shape != (count, 3):
            raise RuntimeDataError("Candidate line phases are not aligned with locations")
        if candidate["response_per_tap_margin_pu"].shape != (count, n_outputs, 3):
            raise RuntimeDataError("Candidate line response is not aligned with ICNN outputs")
    if len(np.unique(data["sites"]["id"])) != n_sites:
        raise RuntimeDataError("Duplicate site IDs in runtime data")
    if int(data["config"]["schema_version"].reshape(-1)[0]) != 1:
        raise RuntimeDataError("Unsupported runtime data schema version")


@lru_cache(maxsize=1)
def load_runtime_data(path: str | Path | None = None) -> dict[str, Any]:
    """Load the single frozen NPZ using ``allow_pickle=False``."""
    if path is None:
        resource = files(__package__).joinpath("data/iowa240_runtime_data.npz")
        with as_file(resource) as resolved:
            return _load_path(resolved)
    return _load_path(Path(path))


def _load_path(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeDataError(f"Runtime data file not found: {path}")
    tree: dict[str, Any] = {}
    try:
        with np.load(path, allow_pickle=False) as raw:
            for key in raw.files:
                _insert(tree, key, raw[key])
    except Exception as exc:
        raise RuntimeDataError(f"Could not load runtime data {path}: {exc}") from exc
    _validate(tree)
    return tree


def site_index(data: dict[str, Any], site_id: str) -> int:
    normalized = str(site_id).strip().lower()
    matches = np.flatnonzero(data["sites"]["id"].astype(str) == normalized)
    if not len(matches):
        available = data["sites"]["id"].astype(str)
        raise ValueError(f"Unknown site_id '{site_id}'. Valid examples: {', '.join(available[:5])}")
    return int(matches[0])
