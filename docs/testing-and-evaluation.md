# Testing And Evaluation

The evaluation helpers live in the API package:

| File | Purpose |
| --- | --- |
| `api/app/evaluation/iou.py` | IoU math |
| `api/app/evaluation/detection_metrics.py` | Detection precision, recall, F1, mAP, per-class metrics, confusion matrix |
| `api/app/evaluation/segmentation_metrics.py` | Dice, pixel accuracy, mask IoU, multiclass mIoU |

## Unit and Integration Tests

Run the full test suite:

```bash
cd api
python -m unittest discover -s tests -v
```

The tests cover IoU math for `xyxy` and `xywh`, precision/recall/F1 at IoU thresholds, class-aware and class-agnostic matching, per-class metrics and confusion matrix, `mAP@0.5`, `mAP@0.5:0.95`, segmentation metrics, API integration, and common failure paths.

`tests/test_api_integration.py` checks `/health`, `/debug/sessions`, `/debug/sessions/history`, unknown session snapshot `404`, no-snapshot-yet `404`, unknown ICE session `404`, and malformed offer payload `422`.

## Extra Dependencies

Install extra benchmark and evaluation dependencies:

```bash
cd api
pip install -r requirements-dev.txt
```

The evaluation scripts live under `models/object_detection/scripts/`. Some scripts import `api/app/evaluation`, so the commands below run from the repository root and set `PYTHONPATH=api` when needed.

## Detection Report

Sample input:

```text
api/examples/detection_eval_sample.json
```

Run:

```bash
PYTHONPATH=api python models/object_detection/scripts/run_detection_eval.py --input api/examples/detection_eval_sample.json
```

Save report:

```bash
PYTHONPATH=api python models/object_detection/scripts/run_detection_eval.py --input api/examples/detection_eval_sample.json --output api/reports/detection_metrics.json
```

Windows PowerShell:

```powershell
$env:PYTHONPATH = "api"
python models\object_detection\scripts\run_detection_eval.py --input api\examples\detection_eval_sample.json
```

## Segmentation Report

Sample input:

```text
api/examples/segmentation_eval_sample.json
```

Run:

```bash
PYTHONPATH=api python models/object_detection/scripts/run_segmentation_eval.py --input api/examples/segmentation_eval_sample.json
```

Save report:

```bash
PYTHONPATH=api python models/object_detection/scripts/run_segmentation_eval.py --input api/examples/segmentation_eval_sample.json --output api/reports/segmentation_metrics.json
```

Windows PowerShell:

```powershell
$env:PYTHONPATH = "api"
python models\object_detection\scripts\run_segmentation_eval.py --input api\examples\segmentation_eval_sample.json
```

## Latency and FPS Benchmark

Run against the required local YOLOv8 model asset:

```bash
python models/object_detection/scripts/run_latency_benchmark.py --model models/object_detection/yolov8n.pt --source 0 --frames 120 --warmup 20
```

`--source` examples:

| Source type | Value |
| --- | --- |
| Webcam | `0` |
| Video file | `some_clip.mp4` |
| Backend snapshot URL | `http://localhost:8000/debug/sessions/<session_id>/latest.jpg` |

## Robustness Evaluation

This evaluates blur, brightness, contrast, JPEG artifacts, and noise perturbations.

Input JSON format:

```json
{
  "images": [
    {
      "image_id": "img-001",
      "path": "C:/path/to/image.jpg",
      "ground_truths": [
        { "label": "person", "bbox": [10, 20, 130, 260] }
      ]
    }
  ]
}
```

Run:

```bash
python models/object_detection/scripts/run_robustness_eval.py --model models/object_detection/yolov8n.pt --input /path/to/robustness_dataset.json --output api/reports/robustness_report.json
```

Windows PowerShell:

```powershell
python models\object_detection\scripts\run_robustness_eval.py --model models\object_detection\yolov8n.pt --input C:\path\to\robustness_dataset.json --output api\reports\robustness_report.json
```

## Regression Check

Compare current metrics with a baseline:

```bash
python models/object_detection/scripts/run_regression_check.py --baseline api/reports/baseline_detection_metrics.json --current api/reports/current_detection_metrics.json --max-map50-drop 0.02 --max-map5095-drop 0.02
```

Set minimum required thresholds:

```bash
python models/object_detection/scripts/run_regression_check.py --current api/reports/current_detection_metrics.json --min-map50 0.40 --min-map5095 0.20
```
