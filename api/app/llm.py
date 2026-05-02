from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_OLLAMA_BASE_URL = "http://host.docker.internal:11434"
DEFAULT_OLLAMA_MODEL = "qwen2.5:7b-instruct"
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 60.0
DEFAULT_OLLAMA_NUM_PREDICT = 180
MAX_CONTEXT_CHARS = 14000
PROMPT_AUDIT_ENABLED_VALUES = {"1", "true", "yes", "on"}
SYSTEM_PROMPT = """You are assisting a visually impaired user.

Use the object detection, segmentation, depth estimation, VLM description, and user question.

Give a short, clear spoken response.
Prioritise immediate obstacles, direction, distance, and safety.
Do not mention raw model names or JSON.
If uncertain, say so briefly. """

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
    context_json = truncate_text(
        json.dumps(scene_context, ensure_ascii=True, sort_keys=True), MAX_CONTEXT_CHARS
    )
    visual_text = vlm_text.strip() if isinstance(vlm_text, str) and vlm_text.strip() else "None"
    user_prompt = (
        f"User question:\n{question}\n\n"
        f"VLM description:\n{visual_text}\n\n"
        "Summarized frame-window context with object detection, segmentation, depth estimation, and direction context:\n"
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
