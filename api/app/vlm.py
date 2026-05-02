from __future__ import annotations

import asyncio
import io
import logging
import os
import threading
from typing import Any

from PIL import Image


SMOLVLM_MODEL_ID = os.getenv(
    "SMOLVLM_MODEL_ID", "HuggingFaceTB/SmolVLM-256M-Instruct"
)
SMOLVLM_MAX_NEW_TOKENS = int(os.getenv("SMOLVLM_MAX_NEW_TOKENS", "120"))
SMOLVLM_NUM_BEAMS = int(os.getenv("SMOLVLM_NUM_BEAMS", "1"))

logger = logging.getLogger("lens-plus.vlm")
_smolvlm_processor: Any | None = None
_smolvlm_model: Any | None = None
_smolvlm_lock = threading.Lock()


class VisionModelError(RuntimeError):
    pass


def get_smolvlm_components() -> tuple[Any, Any, str]:
    global _smolvlm_processor
    global _smolvlm_model

    if _smolvlm_processor is not None and _smolvlm_model is not None:
        return _smolvlm_processor, _smolvlm_model, _model_device()

    with _smolvlm_lock:
        if _smolvlm_processor is None or _smolvlm_model is None:
            try:
                import torch
                from transformers import Idefics3ForConditionalGeneration, Idefics3Processor
            except Exception as error:
                raise VisionModelError(
                    "SmolVLM dependencies are unavailable. Install torch and transformers."
                ) from error

            device = "cuda" if torch.cuda.is_available() else "cpu"
            dtype = torch.float16 if device == "cuda" else torch.float32
            logger.info(
                "Loading SmolVLM model_id=%s device=%s dtype=%s",
                SMOLVLM_MODEL_ID,
                device,
                dtype,
            )
            try:
                processor = Idefics3Processor.from_pretrained(SMOLVLM_MODEL_ID)
                model = Idefics3ForConditionalGeneration.from_pretrained(
                    SMOLVLM_MODEL_ID,
                    torch_dtype=dtype,
                    _attn_implementation="eager",
                ).to(device)
                model.eval()
            except Exception as error:
                raise VisionModelError(f"Failed to load SmolVLM: {error}") from error

            _smolvlm_processor = processor
            _smolvlm_model = model

    return _smolvlm_processor, _smolvlm_model, _model_device()


def _model_device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def clean_generated_answer(answer: str, prompt: str) -> str:
    cleaned = answer.strip()
    if prompt and prompt in cleaned:
        cleaned = cleaned.replace(prompt, "", 1).strip()
    if "Assistant:" in cleaned:
        cleaned = cleaned.split("Assistant:", 1)[1].strip()
    if "User:" in cleaned:
        cleaned = cleaned.split("User:", 1)[0].strip()
    return cleaned.strip()


def query_image_model_sync(image_bytes: bytes, question: str) -> str:
    if not question.strip():
        raise VisionModelError("Question was empty")

    try:
        with Image.open(io.BytesIO(image_bytes)) as source_image:
            image = source_image.convert("RGB")
    except Exception as error:
        raise VisionModelError(f"Could not decode input image: {error}") from error

    processor, model, device = get_smolvlm_components()
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {
                    "type": "text",
                    "text": (
                        "Answer briefly in one short sentence. "
                        "Do not repeat the prompt or include role labels. "
                        f"Question: {question}"
                    ),
                },
            ],
        }
    ]

    try:
        prompt = processor.apply_chat_template(messages, add_generation_prompt=True)
        inputs = processor(text=prompt, images=[image], return_tensors="pt")
        inputs = inputs.to(device)

        import torch

        with torch.inference_mode():
            generated_ids = model.generate(
                **inputs,
                max_new_tokens=SMOLVLM_MAX_NEW_TOKENS,
                do_sample=False,
                num_beams=SMOLVLM_NUM_BEAMS,
                use_cache=True,
            )

        answer = processor.batch_decode(generated_ids, skip_special_tokens=True)[0].strip()
    except Exception as error:
        raise VisionModelError(f"SmolVLM query failed: {error}") from error

    answer = clean_generated_answer(answer, prompt)
    if not answer:
        raise VisionModelError("SmolVLM returned an empty answer")
    return answer


async def query_image_model(image_bytes: bytes, question: str) -> str:
    return await asyncio.to_thread(query_image_model_sync, image_bytes, question)
