# Model Files

The Docker model pipeline expects the required model assets to already exist locally before image build. It does not download model files during Docker build.

All paths below are relative to the repository root.

Download the model files from [LENS-PLUS Dropbox](https://www.dropbox.com/scl/fo/e7wcpej7kzxjdm7qqyulo/AN6OHj5xWruEfk5qEqyan6s?rlkey=gg16nhb58a7rfd0rdv9j75e6p&st=kw2e3fbt&dl=0).

Place the files in these exact locations:

| Asset | Required location |
| --- | --- |
| `yolov8n.pt` | `models/object_detection/` |
| `yolov8n-seg.pt` | `models/segmentation/src/` |
| `deeplabv3plus_mobilenet_finetuned.pth` | `models/segmentation/src/` |
| `DeepLabV3Plus-Pytorch` source checkout | `models/segmentation/src/DeepLabV3Plus-Pytorch/` |
| `depth_anything_v2_metric_hypersim_vits.pth` | `models/depth_estimation/checkpoints/` |

The `DeepLabV3Plus-Pytorch` directory must contain `network/`.

Create the depth checkpoint directory if it does not exist:

```bash
mkdir -p models/depth_estimation/checkpoints
```

If any required local asset is missing, the `model-pipeline` image build fails fast. This prevents the running container from silently depending on external downloads.

Public upstream sources used by this repo include Ultralytics YOLO weights, the DeepLabV3Plus-Pytorch repository, and the Depth Anything V2 metric-depth checkpoint listed in `models/depth_estimation/Depth-Anything-V2/metric_depth/README.md`.

The upstream Depth Anything V2 documentation is kept in place under `models/depth_estimation/Depth-Anything-V2/` so its relative images and links continue to work.
