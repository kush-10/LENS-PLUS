# Architecture

LENS-PLUS is a navigational system for visually impaired users that aims to improve perception of diverse environments with object detection, semantic segmentation, depth estimation, natural language scene generation, and live streaming.

A WebRTC prototype streams video from a phone or desktop browser to a FastAPI backend. The backend stores grouped frame artifacts, accepts voice-question transcripts over the WebRTC data channel, and can answer with scene context, SmolVLM visual text, local Ollama/Qwen, and local TTS audio.

## What Is Implemented

`web/` is a Vite + TypeScript frontend app.

Implemented frontend features:

| Feature | Status |
| --- | --- |
| Camera source | Uses `getUserMedia` for phone testing |
| Video file source | Supports desktop dev testing |
| WebRTC flow | Connect and disconnect flow is implemented |
| Voice questions | Records voice-question transcripts, shows answer text, and plays audio |
| Overlay canvas | Detection-box scaffold is present |

`api/` is a FastAPI + aiortc backend service.

Implemented backend features:

| Feature | Endpoint or behavior |
| --- | --- |
| WebRTC offer | `POST /webrtc/offer` |
| ICE candidate ingest | `POST /webrtc/ice` |
| Health check | `GET /health` |
| Active session debug | `GET /debug/sessions` |
| Session history | `GET /debug/sessions/history` |
| Latest session image | `GET /debug/sessions/{session_id}/latest.jpg` |
| Frame artifacts | Per-session frame dump artifacts in `api/app/session_artifacts/` |
| Data channel questions | Typed messages for `question_text` |
| Assistant pipeline | Summarized frame-window context, SmolVLM, local Ollama/Qwen, and local TTS |

`model-pipeline` is a Docker Compose service and local Python entry point.

Implemented model-pipeline behavior:

| Feature | Behavior |
| --- | --- |
| Entry point | Runs `models/start_pipeline.py --no-video` |
| Artifact watcher | Watches API frame artifacts |
| Sidecars | Writes object detection, segmentation, and depth sidecars |
| Assistant context | Sidecars are consumed by the API when answering questions |

## Repository Layout

| Path | Purpose |
| --- | --- |
| `web/` | Frontend app |
| `api/` | Backend signaling and assistant service |
| `api/README.md` | API-specific overview and links |
| `docs/` | Detailed project documentation |
| `Dockerfile.models` | Model pipeline Docker image |
| `Dockerfile.ollama` | Ollama Docker image wrapper |
| `docker-compose.yml` | Shared dev setup |
| `scripts/setup-dev-https.sh` | Local HTTPS helper for phone camera testing |
| `scripts/clean-session-artifacts.sh` | Session artifact cleanup helper |

## Runtime Flow

1. The browser captures a camera stream or selected video file.
2. The browser connects to the FastAPI backend with WebRTC signaling.
3. The backend samples incoming frames according to `ANALYSIS_TARGET_FPS`.
4. The backend writes grouped frame artifacts and live snapshots.
5. The model pipeline watches completed frame groups and writes object detection, segmentation, and depth sidecars.
6. The user asks a voice question through the WebRTC data channel.
7. The API waits for structured model sidecars, queries SmolVLM for visual text, sends context to Ollama/Qwen, and returns answer text plus optional TTS audio.
