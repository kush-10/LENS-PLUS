# Local Development

Use Docker Compose for the simplest setup. Use the local no-Docker workflow when you want Apple MPS or local NVIDIA CUDA acceleration for the Python model processes.

## Prerequisites

Docker workflow:

| Tool | Version or note |
| --- | --- |
| Docker Desktop | Required for Docker Compose workflow |
| Model files | Required before `model-pipeline` can build |

Local no-Docker workflow:

| Tool | Version or note |
| --- | --- |
| Python | 3.11+ |
| Node.js | 18+ |
| npm | Included with Node.js |
| Ollama | Required for local LLM answers |
| mkcert | Optional, recommended for real phone camera testing |

## Docker Compose

Mac or Linux shell:

```bash
cp .env.example .env
docker compose up --build
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Docker Compose starts four services:

| Service | Purpose |
| --- | --- |
| `ollama` | Hosts the configured local Qwen model through Ollama |
| `api` | Receives WebRTC video, writes grouped frame artifacts, runs VLM/LLM/TTS for questions |
| `model-pipeline` | Runs `models/start_pipeline.py --no-video` and writes model sidecars into the shared artifacts directory |
| `web` | Serves the camera UI |

Open the web app:

```text
http://localhost:5173
```

Verify API health:

```text
http://localhost:8000/health
```

## macOS Local Commands

Use these commands for a local no-Docker run on macOS.

Copy the local Mac env example:

```bash
cp .env.mac.example .env
```

Start the backend:

```bash
python3.12 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r api/requirements.txt torchvision matplotlib
export OLLAMA_BASE_URL=http://localhost:11434
export LENS_COMPUTE_DEVICE=mps
python -m uvicorn app.main:app --app-dir api --host 0.0.0.0 --port 8000 --reload
```

If your Mac only has Python 3.11, use `python3.11 -m venv venv` instead.

Start the model pipeline from a second terminal after the backend is running:

```bash
source venv/bin/activate
export LENS_COMPUTE_DEVICE=mps
python models/start_pipeline.py --no-video
```

Start the frontend from a third terminal:

```bash
cd web
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

Open the web app:

```text
http://localhost:5173
```

## Windows Local Commands

Use these commands from PowerShell for a local no-Docker run on Windows.

Copy the local Windows env example:

```powershell
Copy-Item .env.windows.example .env
```

Start the backend:

```powershell
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r api\requirements.txt torchvision matplotlib
$env:OLLAMA_BASE_URL = "http://localhost:11434"
python -m uvicorn app.main:app --app-dir api --host 0.0.0.0 --port 8000 --reload
```

If `py -3.11` is not available, install Python 3.11+ and rerun the command with the installed launcher version.

Start the model pipeline from a second PowerShell terminal after the backend is running:

```powershell
.\venv\Scripts\Activate.ps1
python models\start_pipeline.py --no-video
```

Start the frontend from a third PowerShell terminal:

```powershell
cd web
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

Open the web app:

```text
http://localhost:5173
```

## Local GPU Commands

Apple Silicon MPS:

```bash
source venv/bin/activate
export LENS_COMPUTE_DEVICE=mps
export OLLAMA_BASE_URL=http://localhost:11434
python -m uvicorn app.main:app --app-dir api --host 0.0.0.0 --port 8000 --reload
```

In a second terminal:

```bash
source venv/bin/activate
export LENS_COMPUTE_DEVICE=mps
python models/start_pipeline.py --no-video
```

NVIDIA CUDA on a local non-Docker machine:

```bash
source venv/bin/activate
export LENS_COMPUTE_DEVICE=cuda
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no cuda')"
export OLLAMA_BASE_URL=http://localhost:11434
python -m uvicorn app.main:app --app-dir api --host 0.0.0.0 --port 8000 --reload
```

In a second terminal:

```bash
source venv/bin/activate
export LENS_COMPUTE_DEVICE=cuda
python models/start_pipeline.py --no-video
```

Windows PowerShell with NVIDIA CUDA:

```powershell
.\venv\Scripts\Activate.ps1
$env:LENS_COMPUTE_DEVICE = "cuda"
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no cuda')"
$env:OLLAMA_BASE_URL = "http://localhost:11434"
python -m uvicorn app.main:app --app-dir api --host 0.0.0.0 --port 8000 --reload
```

In a second PowerShell terminal:

```powershell
.\venv\Scripts\Activate.ps1
$env:LENS_COMPUTE_DEVICE = "cuda"
python models\start_pipeline.py --no-video
```

If CUDA prints `False`, install a CUDA-enabled PyTorch build for your platform from the official PyTorch install selector, then rerun the check. Use `LENS_COMPUTE_DEVICE=cuda:0` to target a specific GPU.

See [GPU Setup](gpu.md) for more detail.
