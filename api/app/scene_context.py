from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FRAME_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp"}


def build_scene_context(
    *,
    artifact_dir: Path | None,
    latest_jpeg_at: datetime | None,
    latest_frame_at: datetime | None,
    latest_directional_context: dict[str, Any] | None,
    latest_detection_context: dict[str, Any] | None,
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "frame": {
            "latest_jpeg_at": latest_jpeg_at.isoformat() if latest_jpeg_at else None,
            "latest_frame_at": latest_frame_at.isoformat() if latest_frame_at else None,
        },
        "directional": latest_directional_context,
        "live_detections": latest_detection_context,
        "artifact": None,
        "frame_metadata": None,
        "object_detection": None,
        "segmentation": None,
        "depth": None,
        "missing_context": [],
        "warnings": [],
    }

    if artifact_dir is None:
        context["missing_context"].append("artifact_dir")
        return context
    if not artifact_dir.exists():
        context["missing_context"].append("artifact_dir_missing")
        return context

    context["artifact"] = {
        "artifact_dir": str(artifact_dir),
        "artifact_id": artifact_dir.name,
    }

    frame_path = find_best_frame_path(artifact_dir)
    if frame_path is None:
        context["missing_context"].append("grouped_frame")
        return context

    context["frame"].update(
        {
            "artifact_frame": frame_path.name,
            "artifact_group": frame_path.parent.name,
        }
    )

    frame_metadata = read_json_file(frame_path.with_suffix(".json"))
    if isinstance(frame_metadata, dict):
        context["frame_metadata"] = frame_metadata
    else:
        context["missing_context"].append("frame_metadata")

    detection_sidecar = read_json_file(frame_path.with_suffix(".detections.json"))
    if isinstance(detection_sidecar, dict):
        context["object_detection"] = detection_sidecar
    else:
        context["missing_context"].append("object_detection_sidecar")

    navigation_sidecar = read_json_file(frame_path.with_suffix(".navigation.json"))
    if isinstance(navigation_sidecar, dict):
        context["segmentation"] = navigation_sidecar.get("segmentation")
        context["depth"] = navigation_sidecar.get("depth")
        if context["segmentation"] is None:
            context["missing_context"].append("segmentation_sidecar")
        if context["depth"] is None:
            context["missing_context"].append("depth_sidecar")
    else:
        context["missing_context"].extend(["segmentation_sidecar", "depth_sidecar"])

    return context


def find_best_frame_path(artifact_dir: Path) -> Path | None:
    groups = sorted(
        [entry for entry in artifact_dir.iterdir() if entry.is_dir() and entry.name.startswith("group-")],
        key=natural_key,
    )
    if not groups:
        return find_latest_frame_in_dir(artifact_dir)

    manifest = read_json_file(artifact_dir / "session.json")
    is_closed = isinstance(manifest, dict) and manifest.get("closed_at") is not None
    complete_groups = groups if is_closed else groups[:-1]
    candidate_groups = complete_groups if complete_groups else groups

    for group in reversed(candidate_groups):
        preferred = find_latest_frame_with_sidecar(group)
        if preferred is not None:
            return preferred

    for group in reversed(candidate_groups):
        latest = find_latest_frame_in_dir(group)
        if latest is not None:
            return latest
    return None


def find_latest_frame_with_sidecar(group_dir: Path) -> Path | None:
    frame_paths = sorted(list_frame_paths(group_dir), key=natural_key, reverse=True)
    for frame_path in frame_paths:
        if frame_path.with_suffix(".detections.json").exists() or frame_path.with_suffix(
            ".navigation.json"
        ).exists():
            return frame_path
    return None


def find_latest_frame_in_dir(directory: Path) -> Path | None:
    frame_paths = sorted(list_frame_paths(directory), key=natural_key, reverse=True)
    return frame_paths[0] if frame_paths else None


def list_frame_paths(directory: Path) -> list[Path]:
    return [
        entry
        for entry in directory.iterdir()
        if entry.is_file() and entry.suffix.lower() in FRAME_EXTENSIONS
    ]


def read_json_file(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def natural_key(path: Path) -> list[Any]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.name)]
