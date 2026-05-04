# API

The Python API handles WebRTC signaling, receives camera frames, throttles analysis to a fixed FPS, stores grouped artifacts, and answers voice-question transcripts over a WebRTC data channel.

It is intentionally lightweight so the model pipeline can be swapped or moved to a separate worker service with minimal API changes.

Core implementation is in `api/app/main.py`.

## Run Locally

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install -r api/requirements.txt torchvision matplotlib
python -m uvicorn app.main:app --app-dir api --host 0.0.0.0 --port 8000 --reload
```

Health check:

```text
http://localhost:8000/health
```

See [Local Development](local-development.md) for Mac, Windows, Docker, and GPU command variants.

## What This API Does

| Capability | Endpoint or behavior |
| --- | --- |
| Accept SDP offer/answer exchange | `POST /webrtc/offer` |
| Accept trickle ICE candidates | `POST /webrtc/ice` |
| Track active sessions and frame counters | `GET /debug/sessions` |
| Return persisted session dump history | `GET /debug/sessions/history` |
| Expose latest JPEG snapshot per session | `GET /debug/sessions/{session_id}/latest.jpg` |
| Write processed session frames to disk | `api/app/session_artifacts/` by default |
| Read model sidecars | `.detections.json` and `.navigation.json` files written beside frames |
| Receive voice-question transcripts | WebRTC data channel message type `question_text` |
| Build answer context | Frame metadata plus sidecars since the previous answer |
| Answer questions | SmolVLM, local Ollama/Qwen, and local TTS |

## Environment Variables

API environment variables are documented in [Environment](environment.md).

Important API defaults:

| Variable | Default | Notes |
| --- | --- | --- |
| `ANALYSIS_TARGET_FPS` | `15` | Clamped to `1..30` |
| `SESSION_ARTIFACTS_DIR` | unset | Defaults to `api/app/session_artifacts` locally and `/app/app/session_artifacts` in Docker |
| `ENABLE_MOCK_RESULTS` | `false` | Enables legacy mock inference ticks |
| `OLLAMA_BASE_URL` | `http://localhost:11434` locally | Docker Compose sets `http://ollama:11434` |
| `OLLAMA_MODEL` | `qwen2.5:1.5b-instruct` | Local Ollama model for final answer composition |
| `OLLAMA_TIMEOUT_SECONDS` | `60` | Ollama request timeout |
| `OLLAMA_NUM_PREDICT` | `180` | Ollama response length control |
| `ENABLE_LLM_PROMPT_AUDIT` | `true` | Writes prompt and answer audits under `question-audits/` |
| `LENS_COMPUTE_DEVICE` | `auto` | Selects CUDA, MPS, or CPU |
| `LENS_VLM_DEVICE` | unset | Optional VLM device override |
| `LENS_DETECTION_DEVICE` | unset | Optional detection device override |
| `LENS_SEGMENTATION_DEVICE` | unset | Optional segmentation device override |
| `LENS_DEPTH_DEVICE` | unset | Optional depth device override |
| `SMOLVLM_MODEL_ID` | `HuggingFaceTB/SmolVLM-256M-Instruct` | Hugging Face model id for local visual-language analysis |
| `SMOLVLM_MAX_NEW_TOKENS` | `120` | SmolVLM generation control |
| `SMOLVLM_NUM_BEAMS` | `1` | SmolVLM generation control |
| `MODEL_CONTEXT_WAIT_TIMEOUT_SECONDS` | `120` | Max wait for model sidecars after a question |
| `MODEL_CONTEXT_POLL_SECONDS` | `0.5` | Poll interval while waiting for sidecars |

Local TTS requires macOS `say` or Linux `espeak-ng`, plus `ffmpeg` for MP3 encoding. The API Dockerfile installs `espeak-ng` and `ffmpeg`.

For local no-Docker GPU use, set `LENS_COMPUTE_DEVICE=mps` on Apple Silicon or `LENS_COMPUTE_DEVICE=cuda` on an NVIDIA CUDA machine before starting the API and `models/start_pipeline.py`.

With Docker Compose, `ANALYSIS_TARGET_FPS` is passed into the `api` container by `docker-compose.yml`:

```yaml
ANALYSIS_TARGET_FPS=${ANALYSIS_TARGET_FPS:-15}
```

## API Contract

### `POST /webrtc/offer`

Request:

```json
{
  "sdp": "...",
  "type": "offer",
  "session_id": "optional"
}
```

Response:

```json
{
  "sdp": "...",
  "type": "answer",
  "session_id": "uuid"
}
```

### `POST /webrtc/ice`

Request:

```json
{
  "session_id": "uuid",
  "candidate": "candidate:...",
  "sdpMid": "0",
  "sdpMLineIndex": 0
}
```

Response:

```json
{
  "ok": true
}
```

### `GET /debug/sessions`

Returns per-session diagnostics, including `analysis_target_fps`, `incoming_fps`, `processed_fps`, `total_frames`, `processed_frames`, `dropped_frames`, snapshot metadata, and connection state.

### `GET /debug/sessions/{session_id}/latest.jpg`

Returns the latest JPEG created from the incoming video track.

### `GET /debug/sessions/history`

Returns persisted session artifact metadata from recent `session.json` files.

## Frame Processing

In `api/app/main.py`, each video frame is received in `consume_frames()`.

Incoming rate is tracked as `incoming_fps`.

Processing is throttled by `analysis_target_fps` using monotonic timing.

Frames skipped by throttling increment `dropped_frames`.

Processed frames increment `processed_frames`.

Each processed frame is saved as a JPEG dump in that session's artifact directory.

A snapshot JPEG is periodically saved for debug preview.

Every session creates `frame-*.jpg` files, `frame-*.json` metadata, and `session.json` metadata with counters, timestamps, dump status, and latest detection state.

`frame-*.json` includes `frame_id`, `frame_index`, `frame_at`, detections, metrics, inference timestamp, staleness, and related metadata.

`app/session_artifacts/` is ignored by git and excluded from Docker build context.

To clear artifacts:

```bash
../scripts/clean-session-artifacts.sh
```

This gives you backpressure control before a real model is attached.

See [Session Artifacts](session-artifacts.md) for artifact details.

## Voice Assistant Data Channel

The frontend sends a text transcript after browser SpeechRecognition stops:

```json
{
  "type": "question_text",
  "text": "What is in front of me?"
}
```

The backend sends status events while the pipeline runs:

```json
{
  "type": "status",
  "status": "running_llm",
  "message": "Composing a navigation answer."
}
```

The final answer includes text and, when local TTS succeeds, MP3 audio as base64:

```json
{
  "type": "answer",
  "transcript": "What is in front of me?",
  "answer": "There is a chair ahead; move slightly left if you need to pass.",
  "audio_base64": "..."
}
```

If structured model sidecars, SmolVLM, the LLM, or TTS fail, the backend still returns the best available text answer and includes `audio_error` when only speech generation fails.
