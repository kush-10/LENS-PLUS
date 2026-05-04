# Session Artifacts

The backend writes per-session processed frame dumps and manifest files to `api/app/session_artifacts/` by default.

In local dev, the default artifact root is:

```text
api/app/session_artifacts
```

In Docker, the default artifact root inside the API container is:

```text
/app/app/session_artifacts
```

Override this path with `SESSION_ARTIFACTS_DIR` for local backend runs.

## Contents

Every session creates grouped processed frames and metadata under a session artifact directory.

Session artifacts include:

| File or directory | Purpose |
| --- | --- |
| `group-*/frame-*.jpg` | Processed frame images |
| `group-*/frame-*.json` | Per-frame metadata |
| `group-*/frame-*.detections.json` | Object detection sidecars from the model pipeline |
| `group-*/frame-*.navigation.json` | Segmentation and depth navigation sidecars from the model pipeline |
| `session.json` | Session counters, timestamps, dump status, and latest detection state |
| `question-audits/` | Optional prompt and answer audits when `ENABLE_LLM_PROMPT_AUDIT=true` |

`frame-*.json` includes frame identifiers, timestamps, detection objects, detection metrics, inference timestamp, staleness, and related metadata.

Object detection entries include labels, confidence values, and bounding boxes.

Detection metrics include `num_detections`, `avg_confidence`, `max_confidence`, and `min_confidence`.

## Cleanup

Use the cleanup helper to remove all stored session dumps and recreate an empty artifact directory:

```bash
scripts/clean-session-artifacts.sh
```

You can also pass a custom artifact path:

```bash
scripts/clean-session-artifacts.sh /tmp/lens-plus-artifacts
```

The helper removes tracked session artifacts from the git index if any were accidentally added.

`api/app/session_artifacts/` is ignored by git and excluded from Docker build context.
