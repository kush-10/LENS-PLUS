from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "qwen2.5:1.5b-instruct"
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 60.0
DEFAULT_OLLAMA_NUM_PREDICT = 180
MAX_CONTEXT_CHARS = 14000
MAX_PROMPT_OBJECTS = 2
PROMPT_AUDIT_ENABLED_VALUES = {"1", "true", "yes", "on"}
SYSTEM_PROMPT = """You are an assistive vision system for a visually impaired user.

INPUT:
- User question
- Object detection data
- Depth data (distance in meters)
- Walkability / segmentation data

CORE RULE:
Always trust structured data over visual description.

GENERAL RULES:
1. Prioritise safety first (distance + obstacles).
2. Only use relevant objects (in front or asked about).
3. Ignore noise and background objects.
4. Keep responses short and clear.
5. Do NOT explain reasoning.
6. If unsure, say "I’m not sure".

---

MODE SELECTION:

If the question is about:
- walking, moving, path, safety → use WALKABILITY MODE
- objects, what is there → use OBJECT MODE

---

WALKABILITY MODE (STRICT OUTPUT):
- Max 1 sentence
- Focus on safety + distance

FORMAT:
[Yes/No]. [Short reason].

EXAMPLES:
Q: Can I walk forward?
A: No. There is an obstacle very close ahead.

Q: Is this walkable?
A: No. Something is directly in front within half a metre.

---

OBJECT MODE (STRICT OUTPUT):
- Max 2 short sentences
- Only closest / most relevant object(s)

FORMAT:
There is [object] [distance] in front. [Optional second object].

EXAMPLES:
Q: What is in front of me?
A: There is a cup about 1 metre in front.

Q: What objects are here?
A: There is a cup about 1 metre in front. A mouse is slightly to the left.

---

IMPORTANT:
- Do NOT mix both modes.
- Do NOT mention walkability in object mode unless explicitly asked.
- Do NOT list more than 2 objects."""

logger = logging.getLogger("lens-plus.ollama")


class OllamaCompletionError(RuntimeError):
    pass


async def generate_assistant_answer(
    *,
    question: str,
    scene_context: dict[str, Any],
    vlm_text: str | None,
    prompt_audit_path: Path | None = None,
) -> str:
    return await asyncio.to_thread(
        generate_assistant_answer_sync,
        question=question,
        scene_context=scene_context,
        vlm_text=vlm_text,
        prompt_audit_path=prompt_audit_path,
    )


def generate_assistant_answer_sync(
    *,
    question: str,
    scene_context: dict[str, Any],
    vlm_text: str | None,
    prompt_audit_path: Path | None = None,
) -> str:
    request_context = build_ollama_chat_request(
        question=question,
        scene_context=scene_context,
        vlm_text=vlm_text,
    )
    endpoint = request_context["endpoint"]
    base_url = request_context["base_url"]
    model = request_context["model"]
    timeout_seconds = request_context["timeout_seconds"]
    context_json = request_context["context_json"]
    visual_text = request_context["visual_text"]
    body = request_context["body"]

    if prompt_audit_path is not None:
        update_prompt_audit(
            prompt_audit_path,
            {
                "llm_request": {
                    "created_at": utc_now_iso(),
                    "endpoint": endpoint,
                    "base_url": base_url,
                    "model": model,
                    "request_body": body,
                    "question_chars": len(question),
                    "context_chars": len(context_json),
                    "vlm_chars": len(visual_text),
                    "context_truncated": context_json.endswith("...[truncated]"),
                }
            },
        )

    logger.info(
        "Running Ollama Qwen request model=%s base_url=%s question_len=%d context_chars=%d vlm_chars=%d audit_path=%s",
        model,
        base_url,
        len(question),
        len(context_json),
        len(visual_text),
        str(prompt_audit_path) if prompt_audit_path else None,
    )
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="ignore").strip()
        logger.warning("Ollama Qwen request failed status=%s detail=%s", error.code, details)
        if prompt_audit_path is not None:
            update_prompt_audit(
                prompt_audit_path,
                {
                    "llm_error": {
                        "failed_at": utc_now_iso(),
                        "type": "HTTPError",
                        "status": error.code,
                        "detail": details,
                    }
                },
            )
        raise OllamaCompletionError(
            f"Ollama request failed with status {error.code}: {details or error.reason}"
        ) from error
    except Exception as error:
        logger.warning("Ollama Qwen request failed: %s", error)
        if prompt_audit_path is not None:
            update_prompt_audit(
                prompt_audit_path,
                {
                    "llm_error": {
                        "failed_at": utc_now_iso(),
                        "type": type(error).__name__,
                        "detail": str(error),
                    }
                },
            )
        raise OllamaCompletionError(f"Ollama request failed: {error}") from error

    try:
        content = payload["message"]["content"]
    except Exception as error:
        if prompt_audit_path is not None:
            update_prompt_audit(
                prompt_audit_path,
                {
                    "llm_error": {
                        "failed_at": utc_now_iso(),
                        "type": "InvalidResponse",
                        "detail": "Ollama response did not include message content",
                        "response_payload": payload,
                    }
                },
            )
        raise OllamaCompletionError("Ollama response did not include message content") from error

    if not isinstance(content, str) or not content.strip():
        if prompt_audit_path is not None:
            update_prompt_audit(
                prompt_audit_path,
                {
                    "llm_error": {
                        "failed_at": utc_now_iso(),
                        "type": "EmptyResponse",
                        "detail": "Ollama returned an empty answer",
                        "response_payload": payload,
                    }
                },
            )
        raise OllamaCompletionError("Ollama returned an empty answer")

    answer = content.strip()
    if prompt_audit_path is not None:
        update_prompt_audit(
            prompt_audit_path,
            {
                "llm_response": {
                    "completed_at": utc_now_iso(),
                    "response_payload": payload,
                    "answer": answer,
                    "answer_chars": len(answer),
                }
            },
        )
    logger.info("Ollama Qwen response generated answer_len=%d", len(answer))
    return answer


def build_ollama_chat_request(
    *,
    question: str,
    scene_context: dict[str, Any],
    vlm_text: str | None,
) -> dict[str, Any]:
    base_url = os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL).strip()
    model = os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL).strip() or DEFAULT_OLLAMA_MODEL
    timeout_seconds = _read_float_env(
        "OLLAMA_TIMEOUT_SECONDS", DEFAULT_OLLAMA_TIMEOUT_SECONDS
    )
    num_predict = _read_int_env("OLLAMA_NUM_PREDICT", DEFAULT_OLLAMA_NUM_PREDICT)
    endpoint = f"{base_url.rstrip('/')}/api/chat"
    llm_scene_context = build_llm_scene_context(scene_context)
    context_json = truncate_text(
        json.dumps(llm_scene_context, ensure_ascii=True, sort_keys=True), MAX_CONTEXT_CHARS
    )
    visual_text = vlm_text.strip() if isinstance(vlm_text, str) and vlm_text.strip() else "None"
    user_prompt = (
        "Answer the user's question using the scene data below. "
        "Use the JSON as the primary source of truth and extract the relevant fields instead of restating it.\n\n"
        f"User question:\n{question}\n\n"
        f"VLM description (supporting only):\n{visual_text}\n\n"
        "Scene context JSON (primary data source):\n"
        f"{context_json}"
    )
    body = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "options": {
            "temperature": 0.2,
            "num_predict": num_predict,
        },
    }
    return {
        "endpoint": endpoint,
        "base_url": base_url,
        "model": model,
        "timeout_seconds": timeout_seconds,
        "context_json": context_json,
        "visual_text": visual_text,
        "body": body,
    }


def build_llm_scene_context(scene_context: dict[str, Any]) -> dict[str, Any]:
    depth = get_dict(scene_context.get("depth"))
    segmentation = get_dict(scene_context.get("segmentation"))
    objects = extract_prompt_objects(scene_context, depth)
    return {
        "objects": objects,
        "nearest_obstacle_m": extract_nearest_obstacle_m(
            scene_context=scene_context,
            depth=depth,
            objects=objects,
        ),
        "walkable": extract_walkable(scene_context=scene_context, segmentation=segmentation),
    }


def extract_prompt_objects(
    scene_context: dict[str, Any], depth: dict[str, Any] | None
) -> list[dict[str, Any]]:
    candidates: list[Any] = []
    for raw_source in [
        scene_context.get("objects"),
        depth.get("objects") if depth is not None else None,
        get_dict(scene_context.get("live_detections"), {}).get("objects"),
        get_dict(scene_context.get("object_detection"), {}).get("detections"),
    ]:
        if isinstance(raw_source, list):
            candidates.extend(raw_source)

    by_label: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        compact_object = compact_prompt_object(candidate)
        if compact_object is None:
            continue
        key = compact_object["label"].lower()
        existing = by_label.get(key)
        if existing is None or should_replace_prompt_object(existing, compact_object):
            by_label[key] = compact_object

    return sorted(
        by_label.values(),
        key=lambda item: (
            item["distance"] is None,
            item["distance"] if item["distance"] is not None else math.inf,
            item["label"],
        ),
    )[:MAX_PROMPT_OBJECTS]


def compact_prompt_object(candidate: Any) -> dict[str, Any] | None:
    if not isinstance(candidate, dict):
        return None

    label = candidate.get("label")
    if not isinstance(label, str) or not label.strip():
        return None

    distance = first_finite_float(
        candidate.get("distance"),
        candidate.get("distance_m"),
        candidate.get("depth_m"),
    )
    return {
        "label": label.strip(),
        "distance": round_distance_m(distance),
        "direction": extract_object_direction(candidate),
    }


def should_replace_prompt_object(
    existing: dict[str, Any], candidate: dict[str, Any]
) -> bool:
    existing_distance = existing.get("distance")
    candidate_distance = candidate.get("distance")
    if existing_distance is None:
        return candidate_distance is not None
    if candidate_distance is None:
        return False
    return candidate_distance < existing_distance


def extract_object_direction(candidate: dict[str, Any]) -> str | None:
    direction = candidate.get("direction")
    if isinstance(direction, str) and direction.strip():
        return normalize_direction(direction)
    return infer_direction_from_bbox(candidate.get("bbox"))


def infer_direction_from_bbox(bbox: Any) -> str | None:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None

    values = [coerce_finite_float(value) for value in bbox]
    if any(value is None for value in values):
        return None
    x, _, width, _ = values
    if x is None or width is None:
        return None
    if not (0.0 <= x <= 1.0 and 0.0 <= width <= 1.0):
        return None

    center_x = x + width / 2.0
    if center_x < 1.0 / 3.0:
        return "left"
    if center_x > 2.0 / 3.0:
        return "right"
    return "ahead"


def normalize_direction(direction: str) -> str:
    lowered = direction.strip().lower().replace("_", " ").replace("-", " ")
    if "left" in lowered:
        return "left"
    if "right" in lowered:
        return "right"
    if "ahead" in lowered or "front" in lowered or "forward" in lowered:
        return "ahead"
    return lowered


def extract_nearest_obstacle_m(
    *,
    scene_context: dict[str, Any],
    depth: dict[str, Any] | None,
    objects: list[dict[str, Any]],
) -> float | None:
    direct_value = first_finite_float(scene_context.get("nearest_obstacle_m"))
    if direct_value is not None:
        return round_distance_m(direct_value)

    if depth is not None:
        depth_value = first_finite_float(depth.get("primary_hazard_m"), depth.get("nearest_m"))
        if depth_value is not None:
            return round_distance_m(depth_value)

    frame_window = get_dict(scene_context.get("frame_window"))
    closest_depth_events = frame_window.get("closest_depth_events") if frame_window else None
    if isinstance(closest_depth_events, list) and closest_depth_events:
        event = get_dict(closest_depth_events[0])
        event_value = first_finite_float(event.get("nearest_m")) if event else None
        if event_value is not None:
            return round_distance_m(event_value)

    object_distances = [
        item.get("distance")
        for item in objects
        if isinstance(item.get("distance"), (int, float))
    ]
    return min(object_distances) if object_distances else None


def extract_walkable(
    *, scene_context: dict[str, Any], segmentation: dict[str, Any] | None
) -> bool | None:
    direct_value = scene_context.get("walkable")
    if isinstance(direct_value, bool):
        return direct_value

    if segmentation is None:
        return None

    return normalize_walkable_status(segmentation.get("walkable_status"))


def normalize_walkable_status(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if not isinstance(value, str):
        return None

    normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
    if normalized in {"unwalkable", "unsafe", "blocked", "blocked_path", "no", "false"}:
        return False
    if normalized in {"walkable", "safe", "clear", "yes", "true"}:
        return True
    return None


def get_dict(value: Any, default: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    return default


def first_finite_float(*values: Any) -> float | None:
    for value in values:
        parsed_value = coerce_finite_float(value)
        if parsed_value is not None:
            return parsed_value
    return None


def coerce_finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    return None


def round_distance_m(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 2)


def truncate_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return f"{value[:max_chars]}...[truncated]"


def prompt_audit_enabled() -> bool:
    return os.getenv("ENABLE_LLM_PROMPT_AUDIT", "true").strip().lower() in PROMPT_AUDIT_ENABLED_VALUES


def update_prompt_audit(path: Path, updates: dict[str, Any]) -> None:
    payload: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text())
            if isinstance(existing, dict):
                payload = existing
        except Exception:
            payload = {}

    payload.update(updates)
    payload["updated_at"] = utc_now_iso()
    write_json_atomic(path, payload)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n")
    temporary_path.replace(path)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_float_env(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


def _read_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default
