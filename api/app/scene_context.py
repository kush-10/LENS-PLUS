from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FRAME_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp"}
MAX_RECENT_FRAMES = 12
MAX_CLOSEST_DEPTH_EVENTS = 10
MAX_TOP_OBJECT_LABELS = 12


def build_scene_context(
    *,
    artifact_dir: Path | None,
    latest_jpeg_at: datetime | None,
    latest_frame_at: datetime | None,
    latest_directional_context: dict[str, Any] | None,
    latest_detection_context: dict[str, Any] | None,
    after_frame_index: int | None = None,
    max_frame_index: int | None = None,
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
        "frame_window": empty_frame_window(
            after_frame_index=after_frame_index,
            max_frame_index=max_frame_index,
        ),
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

    frame_paths = list_artifact_frame_paths(artifact_dir)
    if not frame_paths:
        context["missing_context"].append("artifact_frames")
        return context

    frame_window = summarize_frame_window(
        frame_paths=frame_paths,
        after_frame_index=after_frame_index,
        max_frame_index=max_frame_index,
    )
    context["frame_window"] = frame_window
    context["object_detection"] = frame_window.get("latest_object_detection")
    context["segmentation"] = frame_window.get("latest_segmentation")
    context["depth"] = frame_window.get("latest_depth")

    if frame_window["frames_considered"] == 0:
        context["missing_context"].append("frame_window")
    if frame_window["frames_with_object_detection"] == 0:
        context["missing_context"].append("object_detection_sidecars")
    if frame_window["frames_with_segmentation"] == 0:
        context["missing_context"].append("segmentation_sidecars")
    if frame_window["frames_with_depth"] == 0:
        context["missing_context"].append("depth_sidecars")

    return context


def empty_frame_window(
    *, after_frame_index: int | None, max_frame_index: int | None
) -> dict[str, Any]:
    return {
        "mode": "frames_since_previous_answer",
        "after_frame_index": after_frame_index or 0,
        "max_frame_index": max_frame_index,
        "frames_considered": 0,
        "first_frame_index": None,
        "last_frame_index": None,
        "first_frame_at": None,
        "last_frame_at": None,
        "frames_with_metadata": 0,
        "frames_with_object_detection": 0,
        "frames_with_segmentation": 0,
        "frames_with_depth": 0,
        "missing_sidecar_counts": {
            "frame_metadata": 0,
            "object_detection": 0,
            "segmentation": 0,
            "depth": 0,
        },
        "top_object_labels": [],
        "segmentation_status_counts": {},
        "segmentation_direction_counts": {},
        "closest_depth_events": [],
        "recent_frames": [],
        "latest_object_detection": None,
        "latest_segmentation": None,
        "latest_depth": None,
    }


def summarize_frame_window(
    *,
    frame_paths: list[Path],
    after_frame_index: int | None,
    max_frame_index: int | None,
) -> dict[str, Any]:
    frame_window = empty_frame_window(
        after_frame_index=after_frame_index,
        max_frame_index=max_frame_index,
    )
    after_index = after_frame_index or 0
    object_counts: dict[str, int] = {}
    segmentation_status_counts: dict[str, int] = {}
    segmentation_direction_counts: dict[str, int] = {}
    closest_depth_events: list[dict[str, Any]] = []
    recent_frames: list[dict[str, Any]] = []

    for frame_path in frame_paths:
        frame_metadata = read_json_file(frame_path.with_suffix(".json"))
        frame_index = extract_frame_index(frame_path, frame_metadata)
        if frame_index is None:
            continue
        if frame_index <= after_index:
            continue
        if max_frame_index is not None and frame_index > max_frame_index:
            continue

        frame_window["frames_considered"] += 1
        if frame_window["first_frame_index"] is None:
            frame_window["first_frame_index"] = frame_index
        frame_window["last_frame_index"] = frame_index

        frame_at = extract_frame_at(frame_metadata)
        if frame_at is not None:
            if frame_window["first_frame_at"] is None:
                frame_window["first_frame_at"] = frame_at
            frame_window["last_frame_at"] = frame_at

        if isinstance(frame_metadata, dict):
            frame_window["frames_with_metadata"] += 1
        else:
            frame_window["missing_sidecar_counts"]["frame_metadata"] += 1

        detection_sidecar = read_json_file(frame_path.with_suffix(".detections.json"))
        navigation_sidecar = read_json_file(frame_path.with_suffix(".navigation.json"))
        segmentation = (
            navigation_sidecar.get("segmentation")
            if isinstance(navigation_sidecar, dict)
            else None
        )
        depth = navigation_sidecar.get("depth") if isinstance(navigation_sidecar, dict) else None

        object_labels = summarize_detections(
            detection_sidecar=detection_sidecar,
            object_counts=object_counts,
        )
        if isinstance(detection_sidecar, dict):
            frame_window["frames_with_object_detection"] += 1
            frame_window["latest_object_detection"] = detection_sidecar
        else:
            frame_window["missing_sidecar_counts"]["object_detection"] += 1

        if isinstance(segmentation, dict):
            frame_window["frames_with_segmentation"] += 1
            frame_window["latest_segmentation"] = segmentation
            increment_count(segmentation_status_counts, segmentation.get("walkable_status"))
            increment_count(segmentation_direction_counts, segmentation.get("direction"))
        else:
            frame_window["missing_sidecar_counts"]["segmentation"] += 1

        if isinstance(depth, dict):
            frame_window["frames_with_depth"] += 1
            frame_window["latest_depth"] = depth
            depth_event = build_depth_event(frame_index, frame_at, frame_path, depth)
            if depth_event is not None:
                closest_depth_events.append(depth_event)
        else:
            frame_window["missing_sidecar_counts"]["depth"] += 1

        recent_frames.append(
            build_compact_frame_summary(
                frame_index=frame_index,
                frame_at=frame_at,
                frame_path=frame_path,
                object_labels=object_labels,
                segmentation=segmentation,
                depth=depth,
            )
        )

    frame_window["top_object_labels"] = [
        {"label": label, "count": count}
        for label, count in sorted(
            object_counts.items(), key=lambda item: (-item[1], item[0])
        )[:MAX_TOP_OBJECT_LABELS]
    ]
    frame_window["segmentation_status_counts"] = segmentation_status_counts
    frame_window["segmentation_direction_counts"] = segmentation_direction_counts
    frame_window["closest_depth_events"] = sorted(
        closest_depth_events,
        key=lambda event: (
            event["nearest_m"] if isinstance(event.get("nearest_m"), (int, float)) else float("inf"),
            event["frame_index"],
        ),
    )[:MAX_CLOSEST_DEPTH_EVENTS]
    frame_window["recent_frames"] = recent_frames[-MAX_RECENT_FRAMES:]
    return frame_window


def summarize_detections(
    *, detection_sidecar: Any, object_counts: dict[str, int]
) -> list[str]:
    if not isinstance(detection_sidecar, dict):
        return []

    detections = detection_sidecar.get("detections")
    if not isinstance(detections, list):
        return []

    labels: list[str] = []
    for detection in detections:
        if not isinstance(detection, dict):
            continue
        label = detection.get("label")
        if not isinstance(label, str) or not label:
            continue
        object_counts[label] = object_counts.get(label, 0) + 1
        if label not in labels:
            labels.append(label)
    return labels


def build_depth_event(
    frame_index: int,
    frame_at: str | None,
    frame_path: Path,
    depth: dict[str, Any],
) -> dict[str, Any] | None:
    nearest_m = coerce_float(depth.get("nearest_m"))
    primary_hazard_m = coerce_float(depth.get("primary_hazard_m"))
    event_distance = primary_hazard_m if primary_hazard_m is not None else nearest_m
    if event_distance is None:
        return None

    return {
        "frame_index": frame_index,
        "frame_at": frame_at,
        "frame_name": frame_path.name,
        "nearest_m": event_distance,
        "proximity_status": depth.get("proximity_status"),
        "proximity_detail": depth.get("proximity_detail"),
        "direction_warning": depth.get("direction_warning"),
        "dominant_zone": depth.get("dominant_zone"),
    }


def build_compact_frame_summary(
    *,
    frame_index: int,
    frame_at: str | None,
    frame_path: Path,
    object_labels: list[str],
    segmentation: Any,
    depth: Any,
) -> dict[str, Any]:
    frame_summary: dict[str, Any] = {
        "frame_index": frame_index,
        "frame_at": frame_at,
        "frame_name": frame_path.name,
        "objects": object_labels,
    }
    if isinstance(segmentation, dict):
        frame_summary["segmentation"] = {
            "walkable_status": segmentation.get("walkable_status"),
            "direction": segmentation.get("direction"),
        }
    if isinstance(depth, dict):
        frame_summary["depth"] = {
            "proximity_status": depth.get("proximity_status"),
            "proximity_detail": depth.get("proximity_detail"),
            "nearest_m": depth.get("nearest_m"),
            "primary_hazard_m": depth.get("primary_hazard_m"),
            "direction_warning": depth.get("direction_warning"),
        }
    return frame_summary


def list_artifact_frame_paths(artifact_dir: Path) -> list[Path]:
    return sorted(
        [
            path
            for path in artifact_dir.rglob("*")
            if path.is_file()
            and path.suffix.lower() in FRAME_EXTENSIONS
            and path.name.startswith("frame-")
        ],
        key=natural_key,
    )


def extract_frame_index(frame_path: Path, frame_metadata: Any) -> int | None:
    if isinstance(frame_metadata, dict):
        for key in ["frame_index", "frame_id"]:
            value = frame_metadata.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, float) and value.is_integer():
                return int(value)

    match = re.match(r"frame-(\d+)-", frame_path.name)
    if match:
        return int(match.group(1))
    return None


def extract_frame_at(frame_metadata: Any) -> str | None:
    if not isinstance(frame_metadata, dict):
        return None

    frame_at = frame_metadata.get("frame_at")
    return frame_at if isinstance(frame_at, str) else None


def increment_count(counts: dict[str, int], value: Any) -> None:
    if not isinstance(value, str) or not value:
        return
    counts[value] = counts.get(value, 0) + 1


def coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def read_json_file(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def natural_key(path: Path) -> list[Any]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", str(path))]
