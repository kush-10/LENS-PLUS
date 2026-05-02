from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any


FRAME_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp"}
GROUP_NAME_PATTERN = re.compile(r"^group-(\d+)$")


def empty_missing_counts() -> dict[str, int]:
    return {
        "object_detection": 0,
        "navigation": 0,
        "segmentation": 0,
        "depth": 0,
    }


@dataclass(frozen=True)
class GroupCompleteness:
    group_dir: Path
    group_number: int
    frame_paths: tuple[Path, ...]
    ready: bool
    missing_sidecar_counts: dict[str, int]
    first_frame_index: int | None
    last_frame_index: int | None


@dataclass(frozen=True)
class ModelContextWaitResult:
    ready: bool
    status: str
    reason: str
    waited_seconds: float
    selected_group: str | None = None
    group_number: int | None = None
    frame_count: int = 0
    first_frame_index: int | None = None
    last_frame_index: int | None = None
    missing_sidecar_counts: dict[str, int] = field(default_factory=empty_missing_counts)
    frame_paths: tuple[Path, ...] = ()

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "status": self.status,
            "reason": self.reason,
            "waited_seconds": round(self.waited_seconds, 3),
            "selected_group": self.selected_group,
            "group_number": self.group_number,
            "frame_count": self.frame_count,
            "first_frame_index": self.first_frame_index,
            "last_frame_index": self.last_frame_index,
            "missing_sidecar_counts": dict(self.missing_sidecar_counts),
            "frame_names": [path.name for path in self.frame_paths],
        }


async def wait_for_prior_complete_group(
    *,
    artifact_dir: Path | None,
    session_started_at: datetime,
    question_received_at: datetime,
    group_duration_seconds: float,
    timeout_seconds: float,
    poll_seconds: float,
) -> ModelContextWaitResult:
    started_wait = monotonic()
    candidate = select_latest_prior_group(
        artifact_dir=artifact_dir,
        session_started_at=session_started_at,
        question_received_at=question_received_at,
        group_duration_seconds=group_duration_seconds,
    )
    if candidate is None:
        return ModelContextWaitResult(
            ready=False,
            status="no_prior_group",
            reason="No complete 10-second frame group existed before the question time.",
            waited_seconds=monotonic() - started_wait,
        )

    deadline = started_wait + max(0.0, timeout_seconds)
    poll_interval = max(0.05, poll_seconds)
    last_completeness = candidate

    while True:
        last_completeness = inspect_group_completeness(
            candidate.group_dir,
            group_number=candidate.group_number,
        )
        if last_completeness.ready:
            return build_wait_result(
                completeness=last_completeness,
                ready=True,
                status="ready",
                reason="Structured model context is ready.",
                waited_seconds=monotonic() - started_wait,
            )

        now = monotonic()
        if now >= deadline:
            return build_wait_result(
                completeness=last_completeness,
                ready=False,
                status="timeout",
                reason="Timed out waiting for structured model context.",
                waited_seconds=now - started_wait,
            )

        await asyncio.sleep(min(poll_interval, max(0.0, deadline - now)))


def select_latest_prior_group(
    *,
    artifact_dir: Path | None,
    session_started_at: datetime,
    question_received_at: datetime,
    group_duration_seconds: float,
) -> GroupCompleteness | None:
    if artifact_dir is None or not artifact_dir.exists():
        return None

    question_group_number = group_number_for_time(
        started_at=session_started_at,
        at=question_received_at,
        group_duration_seconds=group_duration_seconds,
    )
    if question_group_number <= 1:
        return None

    candidates: list[tuple[int, Path]] = []
    for group_dir in artifact_dir.iterdir():
        if not group_dir.is_dir():
            continue
        group_number = parse_group_number(group_dir)
        if group_number is None or group_number >= question_group_number:
            continue
        candidates.append((group_number, group_dir))

    for group_number, group_dir in sorted(candidates, key=lambda item: item[0], reverse=True):
        frame_paths = list_group_frame_paths(group_dir)
        if frame_paths:
            return inspect_group_completeness(group_dir, group_number=group_number)

    return None


def inspect_group_completeness(
    group_dir: Path,
    *,
    group_number: int | None = None,
) -> GroupCompleteness:
    resolved_group_number = group_number if group_number is not None else parse_group_number(group_dir)
    frame_paths = tuple(list_group_frame_paths(group_dir))
    missing_counts = empty_missing_counts()
    frame_indices: list[int] = []

    for frame_path in frame_paths:
        frame_index = extract_frame_index(frame_path)
        if frame_index is not None:
            frame_indices.append(frame_index)

        detection_sidecar = read_json_file(frame_path.with_suffix(".detections.json"))
        if not isinstance(detection_sidecar, dict) or not isinstance(
            detection_sidecar.get("detections"),
            list,
        ):
            missing_counts["object_detection"] += 1

        navigation_sidecar = read_json_file(frame_path.with_suffix(".navigation.json"))
        if not isinstance(navigation_sidecar, dict):
            missing_counts["navigation"] += 1
            missing_counts["segmentation"] += 1
            missing_counts["depth"] += 1
            continue

        if not isinstance(navigation_sidecar.get("segmentation"), dict):
            missing_counts["segmentation"] += 1
        if not isinstance(navigation_sidecar.get("depth"), dict):
            missing_counts["depth"] += 1

    ready = bool(frame_paths) and all(count == 0 for count in missing_counts.values())
    return GroupCompleteness(
        group_dir=group_dir,
        group_number=resolved_group_number or 0,
        frame_paths=frame_paths,
        ready=ready,
        missing_sidecar_counts=missing_counts,
        first_frame_index=min(frame_indices) if frame_indices else None,
        last_frame_index=max(frame_indices) if frame_indices else None,
    )


def build_wait_result(
    *,
    completeness: GroupCompleteness,
    ready: bool,
    status: str,
    reason: str,
    waited_seconds: float,
) -> ModelContextWaitResult:
    return ModelContextWaitResult(
        ready=ready,
        status=status,
        reason=reason,
        waited_seconds=waited_seconds,
        selected_group=completeness.group_dir.name,
        group_number=completeness.group_number,
        frame_count=len(completeness.frame_paths),
        first_frame_index=completeness.first_frame_index,
        last_frame_index=completeness.last_frame_index,
        missing_sidecar_counts=dict(completeness.missing_sidecar_counts),
        frame_paths=completeness.frame_paths,
    )


def group_number_for_time(
    *,
    started_at: datetime,
    at: datetime,
    group_duration_seconds: float,
) -> int:
    elapsed_seconds = max(0.0, (at - started_at).total_seconds())
    return int(elapsed_seconds // group_duration_seconds) + 1


def parse_group_number(group_dir: Path) -> int | None:
    match = GROUP_NAME_PATTERN.match(group_dir.name)
    if match is None:
        return None
    return int(match.group(1))


def list_group_frame_paths(group_dir: Path) -> list[Path]:
    return sorted(
        [
            path
            for path in group_dir.iterdir()
            if path.is_file()
            and path.suffix.lower() in FRAME_EXTENSIONS
            and path.name.startswith("frame-")
        ],
        key=natural_key,
    )


def extract_frame_index(frame_path: Path) -> int | None:
    metadata = read_json_file(frame_path.with_suffix(".json"))
    if isinstance(metadata, dict):
        for key in ["frame_index", "frame_id"]:
            value = metadata.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, float) and value.is_integer():
                return int(value)

    match = re.match(r"frame-(\d+)-", frame_path.name)
    if match is not None:
        return int(match.group(1))
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
