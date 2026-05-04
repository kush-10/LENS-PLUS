# Model Pipeline

The model pipeline watches backend frame artifacts and writes sidecar JSON files for assistant context.

Docker Compose starts a separate `model-pipeline` service that runs:

```bash
python -u models/start_pipeline.py --no-video --exit-on-child-failure
```

For local development, start the pipeline from a second terminal after the backend is running:

```bash
source venv/bin/activate
python models/start_pipeline.py --no-video
```

Windows PowerShell:

```powershell
.\venv\Scripts\Activate.ps1
python models\start_pipeline.py --no-video
```

## Required Assets

The model pipeline requires local model files before Docker build or local startup. See [Model Files](model-files.md).

## Services and Sidecars

The API and model service share `api/app/session_artifacts/`.

The integration flow is:

1. The API samples WebRTC frames and writes grouped `frame-*.jpg` artifacts.
2. The model pipeline watches completed groups and writes sidecars next to those frames.
3. Object detection writes `frame-*.detections.json`.
4. Segmentation and depth write `frame-*.navigation.json`.
5. On `question_text`, the API queries SmolVLM with the latest frame while waiting for the latest fully processed group that ended before the question time.
6. A group is ready only when every frame in it has object detection, segmentation, and depth sidecars.
7. If no prior group exists, or if the selected group is still incomplete after `MODEL_CONTEXT_WAIT_TIMEOUT_SECONDS`, the API answers with VLM-only context and marks structured context as not ready.
8. The API sends structured context plus VLM text to Ollama/Qwen, then returns text and TTS audio over the data channel.
9. The metrics summary watcher writes frame-group summaries and LLM question JSON/PNG summaries under `metrics_summaries/`.

The old `send_mock_results()` path remains available only when `ENABLE_MOCK_RESULTS=true`.

## Detection Overlays

If you later want live detection overlays in the browser, map model predictions to the frontend message shape and send serialized JSON over `session.data_channel`.

Expected message shape consumed by the web client:

```json
{
  "timestamp": "2026-04-02T18:29:21.234Z",
  "guidance_text": "Caution: person ahead.",
  "scene_summary": "Detected one person near the center.",
  "objects": [
    {
      "label": "person",
      "confidence": 0.91,
      "bbox": [0.31, 0.22, 0.22, 0.44]
    }
  ]
}
```

`bbox` is normalized `[x, y, width, height]` in `0..1` coordinates.

## Minimal Integration Sketch

Below is a high-level pattern, not drop-in complete code:

```python
loop = asyncio.get_running_loop()
result = await loop.run_in_executor(None, model.predict, model_input)

payload = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "guidance_text": build_guidance(result),
    "scene_summary": summarize_scene(result),
    "objects": to_objects(result),
}

if session.data_channel and getattr(session.data_channel, "readyState", "") == "open":
    session.data_channel.send(json.dumps(payload))
```

## Production Notes

Keep model load as a singleton per process to avoid repeated warmup.

Avoid blocking `track.recv()` with expensive inference on the main event loop.

If inference is slower than configured FPS, keep dropping frames rather than queueing unbounded work.

Consider moving model execution to a separate worker service once load grows.

## GPU

Use local no-Docker runs for Apple MPS or local NVIDIA CUDA acceleration. See [GPU Setup](gpu.md).

The default Docker Compose workflow is CPU-oriented unless you explicitly add GPU runtime settings for your machine.
