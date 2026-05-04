from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path


FFMPEG_BIN = shutil.which("ffmpeg") or "ffmpeg"
SAY_BIN = shutil.which("say")
ESPEAK_BIN = shutil.which("espeak-ng") or shutil.which("espeak")


class AudioProcessingError(RuntimeError):
    pass


def run_subprocess(command: list[str], failure_message: str) -> None:
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as error:
        raise AudioProcessingError(
            f"{failure_message}: missing command {command[0]}"
        ) from error
    except subprocess.CalledProcessError as error:
        details = error.stderr.decode("utf-8", errors="ignore").strip()
        if details:
            raise AudioProcessingError(f"{failure_message}: {details}") from error
        raise AudioProcessingError(failure_message) from error


def synthesize_speech_sync(text: str) -> bytes:
    if not text.strip():
        raise AudioProcessingError("Cannot generate speech for an empty response")

    input_suffix = ".aiff" if SAY_BIN else ".wav"
    with tempfile.NamedTemporaryFile(suffix=input_suffix, delete=False) as input_file:
        input_path = Path(input_file.name)

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as mp3_file:
        mp3_path = Path(mp3_file.name)

    try:
        if SAY_BIN:
            run_subprocess(
                [SAY_BIN, "-o", str(input_path), text],
                "Failed to synthesize speech with the macOS voice engine",
            )
        elif ESPEAK_BIN:
            run_subprocess(
                [ESPEAK_BIN, "-w", str(input_path), text],
                "Failed to synthesize speech with the local voice engine",
            )
        else:
            raise AudioProcessingError(
                "No local TTS engine is available. Install espeak-ng on Linux or use macOS say."
            )

        run_subprocess(
            [
                FFMPEG_BIN,
                "-y",
                "-i",
                str(input_path),
                "-codec:a",
                "libmp3lame",
                "-q:a",
                "4",
                str(mp3_path),
            ],
            "Failed to encode the speech response as MP3",
        )
        return mp3_path.read_bytes()
    finally:
        input_path.unlink(missing_ok=True)
        mp3_path.unlink(missing_ok=True)


async def text_to_speech_bytes(text: str) -> bytes:
    return await asyncio.to_thread(synthesize_speech_sync, text)
