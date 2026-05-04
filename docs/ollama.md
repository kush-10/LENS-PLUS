# Ollama

LENS-PLUS uses Ollama/Qwen for final answer composition after the API gathers structured model context and SmolVLM visual text.

The default model is:

```text
qwen2.5:1.5b-instruct
```

## Docker Compose

Docker Compose builds the `ollama` service from `Dockerfile.ollama` and passes `OLLAMA_MODEL` as a build argument.

Start the stack:

```bash
docker compose up --build
```

The `ollama` service starts `ollama serve`, pulls the configured `OLLAMA_MODEL` into the `ollama-data` Docker volume on first start, and exposes Ollama on port `11434`.

For Docker Compose, keep the API value:

```bash
OLLAMA_BASE_URL=http://ollama:11434
```

To change models, update `.env`:

```bash
OLLAMA_MODEL=qwen2.5:1.5b-instruct
```

Then rebuild:

```bash
docker compose up --build
```

## Local Native Ollama

Install Ollama from [ollama.com](https://ollama.com/download) or with Homebrew on macOS:

```bash
brew install --cask ollama
```

Pull the model:

```bash
ollama pull qwen2.5:1.5b-instruct
```

Start Ollama if it is not already running:

```bash
ollama serve
```

Verify the model responds:

```bash
ollama run qwen2.5:1.5b-instruct "Answer in one short sentence: are you ready?"
```

For local no-Docker API runs, keep:

```bash
OLLAMA_BASE_URL=http://localhost:11434
```

## API Settings

`OLLAMA_MODEL` selects the model name sent to Ollama.

`OLLAMA_BASE_URL` selects the Ollama server URL.

`OLLAMA_TIMEOUT_SECONDS` controls the API request timeout.

`OLLAMA_NUM_PREDICT` controls response length.

`ENABLE_LLM_PROMPT_AUDIT=true` writes the raw prompt and answer audit under each session artifact in `question-audits/`.

## GPU

Native Ollama on Apple Silicon uses Metal acceleration automatically where supported. Use native Ollama on macOS instead of Docker when you want Apple GPU acceleration.

Native Ollama can use NVIDIA GPUs on supported Linux and Windows systems when drivers and CUDA runtime support are installed.

For Dockerized Ollama with NVIDIA GPU, see [GPU Setup](gpu.md).
