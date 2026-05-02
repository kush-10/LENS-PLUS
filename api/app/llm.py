from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any


DEFAULT_OLLAMA_BASE_URL = "http://host.docker.internal:11434"
DEFAULT_OLLAMA_MODEL = "qwen2.5"
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 60.0
DEFAULT_OLLAMA_NUM_PREDICT = 180
MAX_CONTEXT_CHARS = 14000
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
) -> str:
    return await asyncio.to_thread(
        generate_assistant_answer_sync,
        question=question,
        scene_context=scene_context,
        vlm_text=vlm_text,
    )


def generate_assistant_answer_sync(
    *,
    question: str,
    scene_context: dict[str, Any],
    vlm_text: str | None,
) -> str:
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
        "Object detection, segmentation, depth estimation, and direction context:\n"
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

    logger.info(
        "Running Ollama Qwen request model=%s base_url=%s question_len=%d context_chars=%d vlm_chars=%d",
        model,
        base_url,
        len(question),
        len(context_json),
        len(visual_text),
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
        raise OllamaCompletionError(
            f"Ollama request failed with status {error.code}: {details or error.reason}"
        ) from error
    except Exception as error:
        logger.warning("Ollama Qwen request failed: %s", error)
        raise OllamaCompletionError(f"Ollama request failed: {error}") from error

    try:
        content = payload["message"]["content"]
    except Exception as error:
        raise OllamaCompletionError("Ollama response did not include message content") from error

    if not isinstance(content, str) or not content.strip():
        raise OllamaCompletionError("Ollama returned an empty answer")

    answer = content.strip()
    logger.info("Ollama Qwen response generated answer_len=%d", len(answer))
    return answer


def truncate_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return f"{value[:max_chars]}...[truncated]"


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
