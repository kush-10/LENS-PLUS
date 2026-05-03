from __future__ import annotations

import logging
import os
import re
from typing import Any


DEFAULT_DEVICE_ENV = "LENS_COMPUTE_DEVICE"
AUTO_DEVICE_VALUES = {"", "auto", "gpu"}
CUDA_DEVICE_RE = re.compile(r"^cuda(?::(?P<index>\d+))?$")


def select_torch_device(
    *,
    component_env_var: str | None = None,
    allow_mps: bool = True,
    logger: logging.Logger | None = None,
) -> str:
    """Select the best available torch device, with env-var overrides."""

    preference, source = _device_preference(component_env_var)
    try:
        import torch
    except Exception as error:
        _warn(logger, "Torch unavailable while selecting device (%s); using CPU", error)
        return "cpu"

    device = _resolve_device(torch, preference, allow_mps=allow_mps)
    if device is not None:
        return device

    _warn(
        logger,
        "Requested device %r from %s is unavailable; falling back to auto selection",
        preference,
        source,
    )
    return _best_available_device(torch, allow_mps=allow_mps)


def yolo_device_from_torch_device(device: str) -> str:
    """Convert a torch device string into the device format Ultralytics expects."""

    if device == "cuda":
        return "0"
    if device.startswith("cuda:"):
        return device.split(":", 1)[1]
    return device


def _device_preference(component_env_var: str | None) -> tuple[str, str]:
    if component_env_var:
        value = os.getenv(component_env_var, "").strip().lower()
        if value:
            return value, component_env_var

    value = os.getenv(DEFAULT_DEVICE_ENV, "auto").strip().lower()
    return value, DEFAULT_DEVICE_ENV


def _resolve_device(torch: Any, preference: str, *, allow_mps: bool) -> str | None:
    if preference in AUTO_DEVICE_VALUES:
        return _best_available_device(torch, allow_mps=allow_mps)
    if preference == "cpu":
        return "cpu"
    if preference == "mps":
        return "mps" if allow_mps and _mps_available(torch) else None

    cuda_match = CUDA_DEVICE_RE.match(preference)
    if cuda_match:
        if not torch.cuda.is_available():
            return None
        index = cuda_match.group("index")
        if index is None:
            return "cuda"
        if int(index) < torch.cuda.device_count():
            return preference
        return None

    return None


def _best_available_device(torch: Any, *, allow_mps: bool) -> str:
    if torch.cuda.is_available():
        return "cuda"
    if allow_mps and _mps_available(torch):
        return "mps"
    return "cpu"


def _mps_available(torch: Any) -> bool:
    mps_backend = getattr(getattr(torch, "backends", None), "mps", None)
    try:
        return bool(mps_backend is not None and mps_backend.is_available())
    except Exception:
        return False


def _warn(logger: logging.Logger | None, message: str, *args: object) -> None:
    if logger is not None:
        logger.warning(message, *args)
