# Environment

The root `.env.example` is the Docker Compose default. Copy it before running Docker Compose:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Platform-specific examples are also available:

| File | Use case |
| --- | --- |
| `.env.example` | Docker Compose defaults |
| `.env.mac.example` | Local macOS run with native Ollama and Apple Silicon MPS |
| `.env.windows.example` | Local Windows run with native Ollama |
| `.env.nvidia.example` | Local NVIDIA CUDA run with native Ollama |

Vite automatically loads the root `.env` when the frontend starts. Docker Compose automatically reads the root `.env` and passes configured values into services.

The local FastAPI backend and `models/start_pipeline.py` do not automatically load `.env`. Export the values in each backend and model-pipeline terminal, use your shell's dotenv helper, or set only the variables you need before starting each process.

## Docker Defaults

Default `.env.example` values:

```bash
VITE_SIGNALING_BASE_URL=/api
VITE_API_PROXY_TARGET=http://api:8000
DEV_HTTPS=false
DEV_HTTPS_KEY_FILE=/app/certs/dev-key.pem
DEV_HTTPS_CERT_FILE=/app/certs/dev-cert.pem

SNAPSHOT_INTERVAL_SECONDS=0.05
SNAPSHOT_JPEG_QUALITY=92
ANALYSIS_TARGET_FPS=15
ENABLE_MOCK_RESULTS=false
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=qwen2.5:1.5b-instruct
OLLAMA_TIMEOUT_SECONDS=60
OLLAMA_NUM_PREDICT=180
ENABLE_LLM_PROMPT_AUDIT=true
LENS_COMPUTE_DEVICE=auto
LENS_VLM_DEVICE=
LENS_DETECTION_DEVICE=
LENS_SEGMENTATION_DEVICE=
LENS_DEPTH_DEVICE=
SMOLVLM_MODEL_ID=HuggingFaceTB/SmolVLM-256M-Instruct
SMOLVLM_MAX_NEW_TOKENS=120
SMOLVLM_NUM_BEAMS=1
MODEL_CONTEXT_WAIT_TIMEOUT_SECONDS=120
MODEL_CONTEXT_POLL_SECONDS=0.5
```

These defaults target Docker Compose. For a fully local no-Docker run, use `VITE_API_PROXY_TARGET=http://localhost:8000` and point `OLLAMA_BASE_URL` at `http://localhost:11434`.

`VITE_SIGNALING_BASE_URL=/api` keeps browser signaling on the Vite proxy path. This is the safest default for local HTTPS phone testing because it avoids mixed-content errors.

If you do not want to use the Vite `/api` proxy in a fully local no-Docker run, set `VITE_SIGNALING_BASE_URL=http://localhost:8000` instead.

For HTTPS plus Docker phone testing, keep `VITE_SIGNALING_BASE_URL=/api` and `VITE_API_PROXY_TARGET=http://api:8000`. The `scripts/setup-dev-https.sh` helper sets these automatically in Docker mode.

## Variables

`VITE_SIGNALING_BASE_URL` controls the frontend signaling base URL. The default `/api` sends requests through Vite's proxy.

`VITE_API_PROXY_TARGET` controls where Vite proxies `/api` requests. Use `http://api:8000` inside Docker Compose and `http://localhost:8000` for local no-Docker development.

`DEV_HTTPS`, `DEV_HTTPS_KEY_FILE`, and `DEV_HTTPS_CERT_FILE` enable local Vite HTTPS when testing phone cameras over LAN.

`SNAPSHOT_INTERVAL_SECONDS` controls how often backend snapshots are produced. The default is `0.05`, which is about 20 FPS snapshots. The API clamps this to at least `0.03`.

`SNAPSHOT_JPEG_QUALITY` controls backend JPEG quality. Keep this around `90-95` for better detection quality from backend snapshots. The API clamps this to `60..95`.

`ANALYSIS_TARGET_FPS` controls server-side processing cadence. It is clamped to `1..30` and defaults to `15`.

`ENABLE_MOCK_RESULTS=false` disables the legacy mock inference ticks. Set it to `true` only for scaffold testing.

`OLLAMA_BASE_URL` points the API at Ollama. With Docker Compose, `http://ollama:11434` is expected. For fully local no-Docker runs, use `http://localhost:11434`.

`OLLAMA_MODEL` is the local Ollama model used for final answer composition. The default is `qwen2.5:1.5b-instruct`.

`OLLAMA_TIMEOUT_SECONDS` and `OLLAMA_NUM_PREDICT` control Ollama request timeout and response length.

`ENABLE_LLM_PROMPT_AUDIT=true` writes the full raw Ollama/Qwen prompt and answer audit under each session artifact in `question-audits/`.

`LENS_COMPUTE_DEVICE=auto` makes local torch/Ultralytics inference prefer CUDA, then Apple MPS, then CPU. Override globally with `cpu`, `cuda`, `cuda:0`, or `mps`.

`LENS_VLM_DEVICE`, `LENS_DETECTION_DEVICE`, `LENS_SEGMENTATION_DEVICE`, and `LENS_DEPTH_DEVICE` are component-specific overrides. Leave them empty to inherit `LENS_COMPUTE_DEVICE`.

`SMOLVLM_MODEL_ID` sets the Hugging Face model id for local visual-language analysis. The default is `HuggingFaceTB/SmolVLM-256M-Instruct`.

`SMOLVLM_MAX_NEW_TOKENS` and `SMOLVLM_NUM_BEAMS` control SmolVLM generation.

`MODEL_CONTEXT_WAIT_TIMEOUT_SECONDS` is the maximum time to wait for the latest prior frame group to receive detection, segmentation, and depth sidecars after a question is asked.

`MODEL_CONTEXT_POLL_SECONDS` is the poll interval while waiting for model sidecars.

`SESSION_ARTIFACTS_DIR` is an optional backend-only override for the directory where per-session processed frame dumps and manifest files are written. It defaults to `api/app/session_artifacts` in local dev and `/app/app/session_artifacts` in Docker.

## Local TTS

Local TTS uses macOS `say` or Linux `espeak-ng`, then encodes MP3 with `ffmpeg`.

The API Docker image installs `espeak-ng` and `ffmpeg`.

For local macOS runs, `say` is built in. Install `ffmpeg` with Homebrew if MP3 audio output fails:

```bash
brew install ffmpeg
```

For local Linux or WSL runs, install `espeak-ng` and `ffmpeg` with your package manager.
