from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from models.metrics_summary.run_llm_question_summary import LlmQuestionSummaryRunner


class LlmQuestionSummaryTestCase(unittest.TestCase):
    def test_summarises_latency_tokens_and_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifact = Path(tmp_dir) / "20260504T120000000000Z--demo"
            audit_dir = artifact / "question-audits"
            audit_dir.mkdir(parents=True)
            (audit_dir / "question-001.json").write_text(
                json.dumps(
                    {
                        "question": {
                            "text": "What is in front of me?",
                            "chars": 23,
                            "received_at": "2026-05-04T12:00:00+00:00",
                        },
                        "model_context": {
                            "ready": True,
                            "status": "ready",
                            "waited_seconds": 0.25,
                        },
                        "llm_request": {
                            "created_at": "2026-05-04T12:00:01+00:00",
                            "model": "qwen2.5:1.5b-instruct",
                            "endpoint": "http://localhost:11434/api/chat",
                            "question_chars": 23,
                            "context_chars": 140,
                            "vlm_chars": 31,
                        },
                        "llm_response": {
                            "completed_at": "2026-05-04T12:00:02.200000+00:00",
                            "answer": "There is a cup ahead.",
                            "answer_chars": 21,
                            "response_payload": {
                                "total_duration": 1_400_000_000,
                                "load_duration": 100_000_000,
                                "prompt_eval_duration": 300_000_000,
                                "eval_duration": 1_000_000_000,
                                "prompt_eval_count": 52,
                                "eval_count": 20,
                            },
                        },
                        "pipeline_result": {
                            "completed_at": "2026-05-04T12:00:02.500000+00:00",
                            "answer_source": "ollama",
                            "answer": "There is a cup ahead.",
                            "answer_chars": 21,
                            "structured_context_ready": True,
                            "audio_generated": True,
                        },
                    }
                )
                + "\n"
            )

            runner = LlmQuestionSummaryRunner(frames_root=tmp_dir)
            summary_path = runner.summarise_artifact(artifact)

            self.assertIsNotNone(summary_path)
            summary = json.loads(summary_path.read_text())
            self.assertEqual(summary["question_count"], 1)
            self.assertEqual(summary["aggregate_metrics"]["pipeline_wall_ms"]["mean"], 2500.0)
            self.assertEqual(summary["aggregate_metrics"]["llm_wall_ms"]["mean"], 1200.0)
            self.assertEqual(summary["aggregate_metrics"]["ollama_total_ms"]["mean"], 1400.0)
            self.assertEqual(summary["aggregate_metrics"]["prompt_tokens"]["mean"], 52.0)
            self.assertEqual(summary["aggregate_metrics"]["completion_tokens"]["mean"], 20.0)
            self.assertEqual(
                summary["aggregate_metrics"]["completion_tokens_per_second"]["mean"],
                20.0,
            )
            self.assertEqual(summary["outcome_counts"]["answer_sources"], {"ollama": 1})
            self.assertEqual(summary["outcome_counts"]["structured_context_ready"], 1)
            self.assertEqual(summary["outcome_counts"]["audio_generated"], 1)
            if summary["graphical_summary_png"] is None:
                self.assertIn("matplotlib unavailable", summary["graphical_summary_error"])
            else:
                graph_path = summary_path.parent / summary["graphical_summary_png"]
                self.assertTrue(graph_path.exists())


if __name__ == "__main__":
    unittest.main()
