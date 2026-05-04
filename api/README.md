# LENS+ Python API

This service handles WebRTC signaling, receives camera frames, throttles analysis to a fixed FPS, stores grouped artifacts, and answers voice-question transcripts over a WebRTC data channel.

Core implementation is in `app/main.py`.

## Run Locally

```bash
python3.12 -m venv ../venv
source ../venv/bin/activate
pip install -r requirements.txt torchvision matplotlib
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Health check:

```text
http://localhost:8000/health
```

For full Mac, Windows, Docker, Ollama, and GPU setup, use the root README and docs.

## API Docs

| Topic | Link |
| --- | --- |
| API contract, frame processing, and data channel | [`../docs/api.md`](../docs/api.md) |
| Environment variables | [`../docs/environment.md`](../docs/environment.md) |
| Local development commands | [`../docs/local-development.md`](../docs/local-development.md) |
| Model pipeline sidecars | [`../docs/model-pipeline.md`](../docs/model-pipeline.md) |
| Session artifacts and cleanup | [`../docs/session-artifacts.md`](../docs/session-artifacts.md) |
| Testing and evaluation | [`../docs/testing-and-evaluation.md`](../docs/testing-and-evaluation.md) |

## Key Defaults

| Variable | Local default | Docker Compose value |
| --- | --- | --- |
| `ANALYSIS_TARGET_FPS` | `15` | `${ANALYSIS_TARGET_FPS:-15}` |
| `SESSION_ARTIFACTS_DIR` | `app/session_artifacts` | `/app/app/session_artifacts` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | `http://ollama:11434` |
| `OLLAMA_MODEL` | `qwen2.5:1.5b-instruct` | `${OLLAMA_MODEL:-qwen2.5:1.5b-instruct}` |
| `LENS_COMPUTE_DEVICE` | `auto` | `${LENS_COMPUTE_DEVICE:-auto}` |

Local TTS uses macOS `say` or Linux `espeak-ng`, then encodes MP3 with `ffmpeg`. The API Dockerfile installs `espeak-ng` and `ffmpeg`.

Run tests from this directory:

```bash
python -m unittest discover -s tests -v
```
