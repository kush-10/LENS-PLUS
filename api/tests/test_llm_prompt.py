from __future__ import annotations

import json
import unittest

from app.llm import SYSTEM_PROMPT, build_ollama_chat_request


class LlmPromptTestCase(unittest.TestCase):
    def test_system_prompt_prioritizes_structured_data(self) -> None:
        self.assertIn("Always trust structured data over visual description", SYSTEM_PROMPT)
        self.assertIn("Do NOT list more than 2 objects", SYSTEM_PROMPT)

    def test_chat_request_sends_compact_scene_json(self) -> None:
        request_context = build_ollama_chat_request(
            question="What is in front of me?",
            scene_context={
                "frame_window": {"recent_frames": [{"frame_index": 12}]},
                "history": [{"answer": "old"}],
                "metrics": {"latency_ms": 20},
                "depth": {
                    "primary_hazard_m": 0.414,
                    "objects": [
                        {
                            "label": "keyboard",
                            "distance_m": 0.76,
                            "direction": "ahead",
                            "confidence": 0.94,
                        },
                        {
                            "label": "cup",
                            "distance_m": 0.45,
                            "direction": "ahead",
                            "confidence": 0.91,
                            "bbox": [0.3, 0.2, 0.2, 0.2],
                        },
                        {
                            "label": "chair",
                            "distance_m": 1.2,
                            "direction": "on your left",
                        },
                    ],
                },
                "segmentation": {
                    "walkable_status": "WALKABLE",
                    "zone_scores": {"CENTER": 0.8},
                    "inference_latency_ms": 12,
                },
            },
            vlm_text="A hallway.",
        )

        messages = request_context["body"]["messages"]
        user_prompt = messages[1]["content"]
        compact_context = json.loads(request_context["context_json"])

        self.assertEqual(messages[0]["content"], SYSTEM_PROMPT)
        self.assertIn("Use the JSON as the primary source of truth", user_prompt)
        self.assertIn("VLM description (supporting only):", user_prompt)
        self.assertIn("Scene context JSON (primary data source):", user_prompt)
        self.assertEqual(
            compact_context,
            {
                "objects": [
                    {"label": "cup", "distance": 0.45, "direction": "ahead"},
                    {"label": "keyboard", "distance": 0.76, "direction": "ahead"},
                ],
                "nearest_obstacle_m": 0.41,
                "walkable": True,
            },
        )
        self.assertNotIn("frame_window", request_context["context_json"])
        self.assertNotIn("history", request_context["context_json"])
        self.assertNotIn("metrics", request_context["context_json"])
        self.assertNotIn("bbox", request_context["context_json"])
        self.assertNotIn("confidence", request_context["context_json"])


if __name__ == "__main__":
    unittest.main()
