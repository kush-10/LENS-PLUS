# GPU Setup

`LENS_COMPUTE_DEVICE=auto` makes local torch/Ultralytics inference prefer CUDA, then Apple MPS, then CPU.

Supported explicit values include `cpu`, `cuda`, `cuda:0`, and `mps`.

Component-specific overrides are available with `LENS_VLM_DEVICE`, `LENS_DETECTION_DEVICE`, `LENS_SEGMENTATION_DEVICE`, and `LENS_DEPTH_DEVICE`. Leave them empty to inherit `LENS_COMPUTE_DEVICE`.

## macOS Apple Silicon

Use native local Python, not Docker, when you want Apple GPU acceleration for the API VLM and model pipeline.

Docker Desktop on macOS does not expose Apple Metal/MPS acceleration into Linux containers. The Docker workflow should be treated as CPU-only on Mac.

Use native Ollama on macOS for LLM acceleration. Ollama uses Apple's Metal GPU acceleration automatically for supported Apple Silicon Macs when installed natively.

Install Ollama:

```bash
brew install --cask ollama
```

Pull the configured model:

```bash
ollama pull qwen2.5:1.5b-instruct
```

Start or verify Ollama:

```bash
ollama serve
```

In another terminal, verify the model responds:

```bash
ollama run qwen2.5:1.5b-instruct "Answer in one short sentence: are you ready?"
```

Run the backend with MPS:

```bash
source venv/bin/activate
export OLLAMA_BASE_URL=http://localhost:11434
export LENS_COMPUTE_DEVICE=mps
python -m uvicorn app.main:app --app-dir api --host 0.0.0.0 --port 8000 --reload
```

Run the model pipeline with MPS:

```bash
source venv/bin/activate
export LENS_COMPUTE_DEVICE=mps
python models/start_pipeline.py --no-video
```

Verify PyTorch sees MPS:

```bash
python -c "import torch; print(torch.backends.mps.is_available())"
```

If it prints `False`, verify you are on Apple Silicon, using a recent Python/PyTorch build, and not running inside Docker.

## NVIDIA CUDA

Use a local Python environment with CUDA-enabled PyTorch when you want GPU acceleration for the API VLM and model pipeline.

Install the NVIDIA driver and a CUDA-enabled PyTorch build for your platform from the official PyTorch install selector.

Verify PyTorch sees CUDA:

```bash
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no cuda')"
```

Run the backend with CUDA:

```bash
source venv/bin/activate
export OLLAMA_BASE_URL=http://localhost:11434
export LENS_COMPUTE_DEVICE=cuda
python -m uvicorn app.main:app --app-dir api --host 0.0.0.0 --port 8000 --reload
```

Run the model pipeline with CUDA:

```bash
source venv/bin/activate
export LENS_COMPUTE_DEVICE=cuda
python models/start_pipeline.py --no-video
```

Target a specific GPU with `cuda:0`, `cuda:1`, and so on:

```bash
export LENS_COMPUTE_DEVICE=cuda:0
```

Windows PowerShell:

```powershell
$env:LENS_COMPUTE_DEVICE = "cuda"
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no cuda')"
```

## Ollama With NVIDIA GPU

Native Ollama can use NVIDIA GPUs on supported Linux and Windows systems when the NVIDIA driver and CUDA runtime support are installed.

Pull the model:

```bash
ollama pull qwen2.5:1.5b-instruct
```

Verify the model responds:

```bash
ollama run qwen2.5:1.5b-instruct "Answer in one short sentence: are you ready?"
```

If you run Ollama in Docker with NVIDIA GPU, the host needs the NVIDIA Container Toolkit and Docker must be started with GPU access. A direct Docker example is:

```bash
docker run --gpus=all -d -v ollama-data:/root/.ollama -p 11434:11434 --name ollama ollama/ollama
docker exec ollama ollama pull qwen2.5:1.5b-instruct
```

The repository's current `docker-compose.yml` starts Ollama without GPU reservations. It will work for CPU Ollama by default. Add Compose GPU reservations only on machines that have the NVIDIA Container Toolkit configured.

When the API runs locally and Ollama runs in a separate Docker container mapped to the host port, keep:

```bash
export OLLAMA_BASE_URL=http://localhost:11434
```

When the API runs inside this repository's Compose network, keep:

```bash
OLLAMA_BASE_URL=http://ollama:11434
```

## Docker GPU Notes

The default Docker Compose workflow is intended to be portable and should be treated as CPU-only unless you explicitly add GPU runtime settings for your machine.

Apple MPS is not available inside Docker Desktop Linux containers on macOS.

NVIDIA CUDA inside Docker requires NVIDIA drivers, the NVIDIA Container Toolkit, CUDA-compatible container images, and Compose GPU reservations. The current API and model images are slim CPU-oriented images, so local no-Docker CUDA is the documented path for GPU acceleration in this repo.
