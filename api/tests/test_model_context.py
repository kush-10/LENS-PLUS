from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.model_context import select_latest_prior_group, wait_for_prior_complete_group
from app.scene_context import build_scene_context


class ModelContextTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.artifact_dir = Path(self.temp_dir.name)
        self.started_at = datetime(2026, 5, 2, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_selects_latest_group_before_question_group(self) -> None:
        self._complete_frame(self._write_frame(1, 1), "person")
        group_two_frame = self._write_frame(2, 2)
        self._complete_frame(group_two_frame, "chair")
        self._complete_frame(self._write_frame(3, 3), "door")

        result = select_latest_prior_group(
            artifact_dir=self.artifact_dir,
            session_started_at=self.started_at,
            question_received_at=self.started_at + timedelta(seconds=25),
            group_duration_seconds=10,
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.ready)
        self.assertEqual(result.group_dir.name, "group-002")
        self.assertEqual(result.frame_paths, (group_two_frame,))

    async def test_no_prior_group_falls_back_immediately(self) -> None:
        self._complete_frame(self._write_frame(1, 1), "person")

        result = await wait_for_prior_complete_group(
            artifact_dir=self.artifact_dir,
            session_started_at=self.started_at,
            question_received_at=self.started_at + timedelta(seconds=5),
            group_duration_seconds=10,
            timeout_seconds=120,
            poll_seconds=0.01,
        )

        self.assertFalse(result.ready)
        self.assertEqual(result.status, "no_prior_group")
        self.assertLess(result.waited_seconds, 0.1)

    async def test_waits_for_incomplete_prior_group(self) -> None:
        frame_path = self._write_frame(1, 1)
        self._write_detection(frame_path, "person")

        async def complete_sidecar() -> None:
            await asyncio.sleep(0.05)
            self._write_navigation(frame_path)

        asyncio.create_task(complete_sidecar())

        result = await wait_for_prior_complete_group(
            artifact_dir=self.artifact_dir,
            session_started_at=self.started_at,
            question_received_at=self.started_at + timedelta(seconds=12),
            group_duration_seconds=10,
            timeout_seconds=1,
            poll_seconds=0.01,
        )

        self.assertTrue(result.ready)
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.selected_group, "group-001")

    async def test_timeout_uses_vlm_only_path(self) -> None:
        frame_path = self._write_frame(1, 1)
        self._write_detection(frame_path, "person")

        result = await wait_for_prior_complete_group(
            artifact_dir=self.artifact_dir,
            session_started_at=self.started_at,
            question_received_at=self.started_at + timedelta(seconds=12),
            group_duration_seconds=10,
            timeout_seconds=0.05,
            poll_seconds=0.01,
        )

        self.assertFalse(result.ready)
        self.assertEqual(result.status, "timeout")
        self.assertEqual(result.selected_group, "group-001")
        self.assertEqual(result.missing_sidecar_counts["segmentation"], 1)
        self.assertEqual(result.missing_sidecar_counts["depth"], 1)

    async def test_scene_context_can_be_limited_to_selected_group(self) -> None:
        self._complete_frame(self._write_frame(1, 1), "person")
        group_two_frame = self._write_frame(2, 2)
        self._complete_frame(group_two_frame, "chair")

        context = build_scene_context(
            artifact_dir=self.artifact_dir,
            latest_jpeg_at=None,
            latest_frame_at=None,
            latest_directional_context=None,
            latest_detection_context=None,
            frame_paths=[group_two_frame],
        )

        self.assertEqual(context["frame_window"]["frames_considered"], 1)
        self.assertEqual(
            context["frame_window"]["top_object_labels"],
            [{"label": "chair", "count": 1}],
        )

    def _write_frame(self, group_number: int, frame_index: int) -> Path:
        group_dir = self.artifact_dir / f"group-{group_number:03d}"
        group_dir.mkdir(parents=True, exist_ok=True)
        frame_at = self.started_at + timedelta(seconds=frame_index)
        frame_path = group_dir / (
            f"frame-{frame_index:06d}-"
            f"{frame_at.strftime('%Y%m%dT%H%M%S%fZ')}.jpg"
        )
        frame_path.write_bytes(b"jpeg placeholder")
        frame_path.with_suffix(".json").write_text(
            json.dumps(
                {
                    "frame_index": frame_index,
                    "frame_at": frame_at.isoformat(),
                    "group_id": group_number,
                    "group_dir": group_dir.name,
                }
            )
        )
        return frame_path

    def _complete_frame(self, frame_path: Path, label: str) -> None:
        self._write_detection(frame_path, label)
        self._write_navigation(frame_path)

    def _write_detection(self, frame_path: Path, label: str) -> None:
        frame_path.with_suffix(".detections.json").write_text(
            json.dumps(
                {
                    "detections": [
                        {
                            "label": label,
                            "confidence": 0.9,
                            "xyxy": [1, 2, 3, 4],
                        }
                    ]
                }
            )
        )

    def _write_navigation(self, frame_path: Path) -> None:
        frame_path.with_suffix(".navigation.json").write_text(
            json.dumps(
                {
                    "segmentation": {
                        "walkable_status": "safe",
                        "direction": "forward",
                    },
                    "depth": {
                        "nearest_m": 2.0,
                        "primary_hazard_m": 2.0,
                        "proximity_status": "clear",
                    },
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
