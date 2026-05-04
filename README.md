# LENS-PLUS

Local Environmental Navigation Support +

LENS-PLUS streams video from a phone or desktop browser to a FastAPI backend, writes frame artifacts, runs local vision models, and answers navigation questions with SmolVLM, Ollama/Qwen, and local TTS.

## Before You Run

Download and place the required model files first. The Docker `model-pipeline` build fails if they are missing.

See [Model Files](docs/model-files.md) for the Dropbox link and exact paths.

## Install Docker

Mac:

```bash
brew install --cask docker
open -a Docker
docker --version
```

You can also install Docker Desktop from [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/).

Windows PowerShell:

```powershell
winget install Docker.DockerDesktop
```

After install, start Docker Desktop, enable WSL 2 integration if prompted, then verify:

```powershell
docker --version
docker compose version
```

## Docker Commands

Mac:

```bash
cp .env.example .env
docker compose up --build
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Open the app:

```text
http://localhost:5173
```

Check the API:

```text
http://localhost:8000/health
```

Docker Compose starts `ollama`, `api`, `model-pipeline`, and `web`. The `ollama` service pulls `OLLAMA_MODEL` into the `ollama-data` volume on first start.

## Mac Local Commands

Use this no-Docker workflow when you want local Apple MPS GPU acceleration or faster iteration.

Backend terminal:

```bash
cp .env.mac.example .env
python3.12 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r api/requirements.txt torchvision matplotlib
export OLLAMA_BASE_URL=http://localhost:11434
export LENS_COMPUTE_DEVICE=mps
python -m uvicorn app.main:app --app-dir api --host 0.0.0.0 --port 8000 --reload
```

Model pipeline terminal:

```bash
source venv/bin/activate
export LENS_COMPUTE_DEVICE=mps
python models/start_pipeline.py --no-video
```

Frontend terminal:

```bash
cd web
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

If your Mac only has Python 3.11, use `python3.11 -m venv venv` instead of `python3.12 -m venv venv`.

## Windows Local Commands

Use this no-Docker workflow from PowerShell.

Backend terminal:

```powershell
Copy-Item .env.windows.example .env
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r api\requirements.txt torchvision matplotlib
$env:OLLAMA_BASE_URL = "http://localhost:11434"
python -m uvicorn app.main:app --app-dir api --host 0.0.0.0 --port 8000 --reload
```

Model pipeline terminal:

```powershell
.\venv\Scripts\Activate.ps1
python models\start_pipeline.py --no-video
```

Frontend terminal:

```powershell
cd web
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

## Ollama Model

Default model:

```text
qwen2.5:1.5b-instruct
```

Docker Compose pulls this automatically through the `ollama` service. For Docker, keep:

```bash
OLLAMA_BASE_URL=http://ollama:11434
```

For local no-Docker runs, install Ollama and pull the model yourself:

```bash
ollama pull qwen2.5:1.5b-instruct
ollama run qwen2.5:1.5b-instruct "Answer in one short sentence: are you ready?"
```

For local no-Docker API runs, keep:

```bash
OLLAMA_BASE_URL=http://localhost:11434
```

See [Ollama](docs/ollama.md) for Docker, native, model, and audit settings.

## Mac GPU

Use native local Python and native Ollama on Apple Silicon.

Ollama uses Apple's Metal GPU acceleration automatically when installed natively on supported Macs. Docker Desktop on macOS does not expose Apple MPS/Metal acceleration to Linux containers.

Install native Ollama:

```bash
brew install --cask ollama
ollama pull qwen2.5:1.5b-instruct
```

Run API and model pipeline with Apple MPS:

```bash
export LENS_COMPUTE_DEVICE=mps
export OLLAMA_BASE_URL=http://localhost:11434
python -c "import torch; print(torch.backends.mps.is_available())"
```

Start the backend and model pipeline from terminals that have `LENS_COMPUTE_DEVICE=mps` exported.

## NVIDIA GPU

For local Python GPU acceleration, install NVIDIA drivers and a CUDA-enabled PyTorch build, then run:

```bash
export LENS_COMPUTE_DEVICE=cuda
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no cuda')"
```

Use `LENS_COMPUTE_DEVICE=cuda:0` to target a specific GPU.

Start the backend and model pipeline from terminals that have `LENS_COMPUTE_DEVICE=cuda` exported.

For native Ollama with NVIDIA, pull and run the model normally after NVIDIA driver setup:

```bash
ollama pull qwen2.5:1.5b-instruct
ollama run qwen2.5:1.5b-instruct "Answer in one short sentence: are you ready?"
```

For Dockerized Ollama with NVIDIA GPU, install NVIDIA Container Toolkit and start Ollama with GPU access:

```bash
docker run --gpus=all -d -v ollama-data:/root/.ollama -p 11434:11434 --name ollama ollama/ollama
docker exec ollama ollama pull qwen2.5:1.5b-instruct
```

The repository's default `docker-compose.yml` is CPU-oriented unless you add GPU runtime settings for your NVIDIA machine. See [GPU Setup](docs/gpu.md).

## Scripts

| Script | Use |
| --- | --- |
| [`scripts/setup-dev-https.sh`](scripts/setup-dev-https.sh) | Generates mkcert HTTPS certs and updates `.env` for LAN phone camera testing. See [Phone Testing](docs/phone-testing.md). |
| [`scripts/clean-session-artifacts.sh`](scripts/clean-session-artifacts.sh) | Removes stored session frame artifacts and recreates an empty artifact directory. See [Session Artifacts](docs/session-artifacts.md). |

## Docs

| Topic | Link |
| --- | --- |
| Architecture and repository layout | [docs/architecture.md](docs/architecture.md) |
| Helper scripts | [scripts/](scripts/) |
| Model files and required weights | [docs/model-files.md](docs/model-files.md) |
| Environment variables and env examples | [docs/environment.md](docs/environment.md) |
| Local development commands | [docs/local-development.md](docs/local-development.md) |
| Ollama setup | [docs/ollama.md](docs/ollama.md) |
| GPU setup | [docs/gpu.md](docs/gpu.md) |
| Phone/LAN HTTPS testing | [docs/phone-testing.md](docs/phone-testing.md) |
| API contract and data channel | [docs/api.md](docs/api.md) |
| Model pipeline and sidecars | [docs/model-pipeline.md](docs/model-pipeline.md) |
| Testing and evaluation | [docs/testing-and-evaluation.md](docs/testing-and-evaluation.md) |
| Session artifacts and cleanup | [docs/session-artifacts.md](docs/session-artifacts.md) |
