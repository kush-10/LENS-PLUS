#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parents[1]
APP_DIR = PROJECT_ROOT / "api" / "app"

SUMMARY_FILENAME = "llm-questions.summary.json"
SUMMARY_PNG_FILENAME = "llm-questions.summary.png"


def natural_key(path: Path) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", path.name)]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    return None


def safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return None


def numeric_stats(values: list[float | None]) -> dict:
    clean = sorted(v for v in values if v is not None)
    if not clean:
        return {"count": 0}

    return {
        "count": len(clean),
        "mean": round(sum(clean) / len(clean), 4),
        "min": round(clean[0], 4),
        "max": round(clean[-1], 4),
        "p50": round(percentile(clean, 50), 4),
        "p90": round(percentile(clean, 90), 4),
        "p95": round(percentile(clean, 95), 4),
        "p99": round(percentile(clean, 99), 4),
    }


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    idx = int(round((pct / 100.0) * (len(values) - 1)))
    return values[idx]


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None

    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def elapsed_ms(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None

    return max(0.0, (end - start).total_seconds() * 1000.0)


def ns_to_ms(value: Any) -> float | None:
    raw = safe_float(value)
    if raw is None:
        return None
    return raw / 1_000_000.0


def get_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


class LlmQuestionSummaryRunner:
    def __init__(self, frames_root: str, interval: float = 2.0):
        self.frames_root = Path(frames_root)
        self.interval = max(0.5, float(interval))

    def get_artifacts(self) -> list[Path]:
        if not self.frames_root.exists():
            return []

        artifacts = [p for p in self.frames_root.iterdir() if p.is_dir()]
        artifacts.sort(key=natural_key)
        return artifacts

    def resolve_artifact(self, artifact: str) -> Path:
        path = Path(artifact).expanduser()
        if path.is_absolute():
            return path
        return self.frames_root / path

    def get_audit_paths(self, artifact: Path) -> list[Path]:
        audit_dir = artifact / "question-audits"
        if not audit_dir.exists():
            return []

        audits = [p for p in audit_dir.iterdir() if p.is_file() and p.suffix == ".json"]
        audits.sort(key=natural_key)
        return audits

    def latest_artifact_with_audits(self) -> Path | None:
        for artifact in reversed(self.get_artifacts()):
            if self.get_audit_paths(artifact):
                return artifact
        return None

    def summary_is_current(self, artifact: Path) -> bool:
        audit_paths = self.get_audit_paths(artifact)
        if not audit_paths:
            return True

        summary_dir = artifact / "metrics_summaries"
        summary_path = summary_dir / SUMMARY_FILENAME
        png_path = summary_dir / SUMMARY_PNG_FILENAME
        if not summary_path.exists():
            return False
        if not png_path.exists():
            summary_data = read_json(summary_path)
            if summary_data.get("graphical_summary_error"):
                try:
                    import matplotlib  # noqa: F401
                except ImportError:
                    return summary_path.stat().st_mtime >= max(
                        path.stat().st_mtime for path in audit_paths
                    )
                return False
            return False

        latest_input_mtime = max(path.stat().st_mtime for path in audit_paths)
        output_mtime = min(summary_path.stat().st_mtime, png_path.stat().st_mtime)
        return output_mtime >= latest_input_mtime

    def collect_question_metric(self, audit_path: Path) -> dict[str, Any] | None:
        audit = read_json(audit_path)
        if not audit:
            return None

        question = get_dict(audit.get("question"))
        llm_request = get_dict(audit.get("llm_request"))
        llm_response = get_dict(audit.get("llm_response"))
        response_payload = get_dict(llm_response.get("response_payload"))
        pipeline_result = get_dict(audit.get("pipeline_result"))
        model_context = get_dict(audit.get("model_context"))
        llm_error = get_dict(audit.get("llm_error"))

        prompt_tokens = safe_int(response_payload.get("prompt_eval_count"))
        completion_tokens = safe_int(response_payload.get("eval_count"))
        total_tokens = None
        if prompt_tokens is not None or completion_tokens is not None:
            total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)

        eval_duration_ns = safe_float(response_payload.get("eval_duration"))
        tokens_per_second = None
        if completion_tokens is not None and eval_duration_ns is not None and eval_duration_ns > 0:
            tokens_per_second = completion_tokens / (eval_duration_ns / 1_000_000_000.0)

        question_received_at = parse_datetime(question.get("received_at"))
        pipeline_completed_at = parse_datetime(pipeline_result.get("completed_at"))
        llm_started_at = parse_datetime(llm_request.get("created_at"))
        llm_completed_at = parse_datetime(llm_response.get("completed_at"))

        answer = pipeline_result.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            answer = llm_response.get("answer")

        answer_source = pipeline_result.get("answer_source")
        if not isinstance(answer_source, str) or not answer_source.strip():
            answer_source = "ollama" if llm_response else "unknown"

        structured_context_ready = pipeline_result.get("structured_context_ready")
        if not isinstance(structured_context_ready, bool):
            structured_context_ready = model_context.get("ready")

        model_context_waited_seconds = safe_float(model_context.get("waited_seconds"))

        return {
            "audit_file": audit_path.name,
            "question": question.get("text"),
            "answer": answer,
            "model": llm_request.get("model"),
            "endpoint": llm_request.get("endpoint"),
            "latency_ms": {
                "pipeline_wall": elapsed_ms(question_received_at, pipeline_completed_at),
                "llm_wall": elapsed_ms(llm_started_at, llm_completed_at),
                "ollama_total": ns_to_ms(response_payload.get("total_duration")),
                "ollama_load": ns_to_ms(response_payload.get("load_duration")),
                "ollama_prompt_eval": ns_to_ms(response_payload.get("prompt_eval_duration")),
                "ollama_completion_eval": ns_to_ms(response_payload.get("eval_duration")),
                "model_context_wait": (
                    model_context_waited_seconds * 1000.0
                    if model_context_waited_seconds is not None
                    else None
                ),
            },
            "tokens": {
                "prompt": prompt_tokens,
                "completion": completion_tokens,
                "total": total_tokens,
                "completion_tokens_per_second": tokens_per_second,
            },
            "chars": {
                "question": safe_int(llm_request.get("question_chars")) or safe_int(question.get("chars")),
                "context": safe_int(llm_request.get("context_chars")),
                "vlm": safe_int(llm_request.get("vlm_chars")),
                "answer": safe_int(pipeline_result.get("answer_chars"))
                or safe_int(llm_response.get("answer_chars")),
            },
            "outcome": {
                "answer_source": answer_source,
                "structured_context_ready": structured_context_ready,
                "model_context_status": model_context.get("status"),
                "audio_generated": pipeline_result.get("audio_generated"),
                "llm_error_type": llm_error.get("type"),
                "llm_error_detail": llm_error.get("detail"),
            },
        }

    def collect_artifact_metrics(self, artifact: Path) -> list[dict[str, Any]]:
        metrics = []
        for audit_path in self.get_audit_paths(artifact):
            metric = self.collect_question_metric(audit_path)
            if metric is not None:
                metrics.append(metric)
        return metrics

    def _metric_series(
        self,
        question_metrics: list[dict[str, Any]],
        section: str,
        key: str,
    ) -> list[float | None]:
        return [
            safe_float(get_dict(metric.get(section)).get(key))
            for metric in question_metrics
        ]

    def _plot_series(
        self,
        ax: Any,
        x_vals: list[int],
        values: list[float | None],
        label: str,
        color: str,
    ) -> bool:
        clean = [(x, y) for x, y in zip(x_vals, values) if y is not None]
        if not clean:
            return False
        xs, ys = zip(*clean)
        ax.plot(xs, ys, marker="o", markersize=4, linewidth=1.6, label=label, color=color)
        return True

    def _set_empty_axis(self, ax: Any, title: str, message: str = "No data") -> None:
        ax.set_title(title)
        ax.text(0.5, 0.5, message, ha="center", va="center", transform=ax.transAxes)
        ax.set_xticks([])
        ax.set_yticks([])

    def save_graphical_summary(
        self,
        png_path: Path,
        artifact_name: str,
        question_metrics: list[dict[str, Any]],
    ) -> str | None:
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError as error:
            return f"matplotlib unavailable: {error}"

        question_count = len(question_metrics)
        x_vals = list(range(1, question_count + 1))

        pipeline_wall = self._metric_series(question_metrics, "latency_ms", "pipeline_wall")
        llm_wall = self._metric_series(question_metrics, "latency_ms", "llm_wall")
        ollama_total = self._metric_series(question_metrics, "latency_ms", "ollama_total")
        ollama_load = self._metric_series(question_metrics, "latency_ms", "ollama_load")
        ollama_prompt_eval = self._metric_series(question_metrics, "latency_ms", "ollama_prompt_eval")
        ollama_completion_eval = self._metric_series(
            question_metrics,
            "latency_ms",
            "ollama_completion_eval",
        )
        model_context_wait = self._metric_series(question_metrics, "latency_ms", "model_context_wait")
        prompt_tokens = self._metric_series(question_metrics, "tokens", "prompt")
        completion_tokens = self._metric_series(question_metrics, "tokens", "completion")
        total_tokens = self._metric_series(question_metrics, "tokens", "total")
        tokens_per_second = self._metric_series(
            question_metrics,
            "tokens",
            "completion_tokens_per_second",
        )
        question_chars = self._metric_series(question_metrics, "chars", "question")
        context_chars = self._metric_series(question_metrics, "chars", "context")
        vlm_chars = self._metric_series(question_metrics, "chars", "vlm")
        answer_chars = self._metric_series(question_metrics, "chars", "answer")

        fig, axes = plt.subplots(3, 3, figsize=(24, 15))
        fig.suptitle(f"LLM Question Summary: {artifact_name}", fontsize=15, fontweight="bold")

        ax = axes[0, 0]
        plotted = False
        plotted |= self._plot_series(ax, x_vals, pipeline_wall, "pipeline wall", "#1f77b4")
        plotted |= self._plot_series(ax, x_vals, llm_wall, "llm wall", "#ff7f0e")
        plotted |= self._plot_series(ax, x_vals, ollama_total, "ollama total", "#2ca02c")
        plotted |= self._plot_series(ax, x_vals, model_context_wait, "context wait", "#9467bd")
        if plotted:
            ax.set_title("Question Latency Timeline")
            ax.set_xlabel("Question index")
            ax.set_ylabel("Latency (ms)")
            ax.grid(alpha=0.25)
            ax.legend(loc="upper right", fontsize=8)
        else:
            self._set_empty_axis(ax, "Question Latency Timeline")

        ax = axes[0, 1]
        plotted = False
        plotted |= self._plot_series(ax, x_vals, ollama_load, "load", "#8c564b")
        plotted |= self._plot_series(ax, x_vals, ollama_prompt_eval, "prompt eval", "#1f77b4")
        plotted |= self._plot_series(ax, x_vals, ollama_completion_eval, "completion eval", "#d62728")
        if plotted:
            ax.set_title("Ollama Latency Breakdown")
            ax.set_xlabel("Question index")
            ax.set_ylabel("Latency (ms)")
            ax.grid(alpha=0.25)
            ax.legend(loc="upper right", fontsize=8)
        else:
            self._set_empty_axis(ax, "Ollama Latency Breakdown")

        ax = axes[0, 2]
        plotted = False
        plotted |= self._plot_series(ax, x_vals, prompt_tokens, "prompt", "#1f77b4")
        plotted |= self._plot_series(ax, x_vals, completion_tokens, "completion", "#ff7f0e")
        plotted |= self._plot_series(ax, x_vals, total_tokens, "total", "#2ca02c")
        if plotted:
            ax.set_title("Token Usage")
            ax.set_xlabel("Question index")
            ax.set_ylabel("Tokens")
            ax.grid(alpha=0.25)
            ax.legend(loc="upper right", fontsize=8)
        else:
            self._set_empty_axis(ax, "Token Usage")

        ax = axes[1, 0]
        if self._plot_series(ax, x_vals, tokens_per_second, "completion tok/s", "#17becf"):
            ax.set_title("Completion Throughput")
            ax.set_xlabel("Question index")
            ax.set_ylabel("Tokens / second")
            ax.grid(alpha=0.25)
            ax.legend(loc="upper right", fontsize=8)
        else:
            self._set_empty_axis(ax, "Completion Throughput")

        ax = axes[1, 1]
        plotted = False
        plotted |= self._plot_series(ax, x_vals, question_chars, "question", "#1f77b4")
        plotted |= self._plot_series(ax, x_vals, context_chars, "context", "#9467bd")
        plotted |= self._plot_series(ax, x_vals, vlm_chars, "vlm", "#ff7f0e")
        plotted |= self._plot_series(ax, x_vals, answer_chars, "answer", "#2ca02c")
        if plotted:
            ax.set_title("Prompt and Answer Size")
            ax.set_xlabel("Question index")
            ax.set_ylabel("Characters")
            ax.grid(alpha=0.25)
            ax.legend(loc="upper right", fontsize=8)
        else:
            self._set_empty_axis(ax, "Prompt and Answer Size")

        ax = axes[1, 2]
        latency_sets = []
        latency_labels = []
        for label, values in [
            ("Pipeline", pipeline_wall),
            ("LLM", llm_wall),
            ("Ollama", ollama_total),
            ("Context", model_context_wait),
        ]:
            clean = [value for value in values if value is not None]
            if clean:
                latency_sets.append(clean)
                latency_labels.append(label)
        if latency_sets:
            ax.boxplot(latency_sets, labels=latency_labels, patch_artist=True)
            ax.set_title("Latency Distribution")
            ax.set_ylabel("Latency (ms)")
            ax.grid(alpha=0.25, axis="y")
        else:
            self._set_empty_axis(ax, "Latency Distribution")

        ax = axes[2, 0]
        structured_ready = [
            1.0 if metric["outcome"].get("structured_context_ready") is True else 0.0
            for metric in question_metrics
        ]
        audio_generated = [
            1.0 if metric["outcome"].get("audio_generated") is True else 0.0
            for metric in question_metrics
        ]
        fallback_answer = [
            1.0 if metric["outcome"].get("answer_source") != "ollama" else 0.0
            for metric in question_metrics
        ]
        llm_error = [
            1.0 if metric["outcome"].get("llm_error_type") else 0.0
            for metric in question_metrics
        ]
        plotted = False
        plotted |= self._plot_series(ax, x_vals, structured_ready, "context ready", "#2ca02c")
        plotted |= self._plot_series(ax, x_vals, audio_generated, "audio", "#1f77b4")
        plotted |= self._plot_series(ax, x_vals, fallback_answer, "fallback", "#ff7f0e")
        plotted |= self._plot_series(ax, x_vals, llm_error, "llm error", "#d62728")
        if plotted:
            ax.set_title("Outcome Timeline")
            ax.set_xlabel("Question index")
            ax.set_ylabel("0 / 1")
            ax.set_ylim(-0.05, 1.05)
            ax.grid(alpha=0.25)
            ax.legend(loc="lower right", fontsize=8)
        else:
            self._set_empty_axis(ax, "Outcome Timeline")

        ax = axes[2, 1]
        answer_sources = Counter(
            metric["outcome"].get("answer_source") or "unknown"
            for metric in question_metrics
        )
        labels = list(answer_sources.keys())
        values = [answer_sources[label] for label in labels]
        if labels:
            ax.bar(labels, values, color="#1f77b4", alpha=0.85)
            ax.set_title("Answer Source Counts")
            ax.set_ylabel("Questions")
            ax.grid(alpha=0.25, axis="y")
        else:
            self._set_empty_axis(ax, "Answer Source Counts")

        ax = axes[2, 2]
        pipeline_stats = numeric_stats(pipeline_wall)
        llm_stats = numeric_stats(llm_wall)
        token_stats = numeric_stats(total_tokens)
        throughput_stats = numeric_stats(tokens_per_second)
        summary_lines = [
            f"questions: {question_count}",
            f"avg pipeline ms: {pipeline_stats.get('mean', 'n/a')}",
            f"p95 pipeline ms: {pipeline_stats.get('p95', 'n/a')}",
            f"avg llm ms: {llm_stats.get('mean', 'n/a')}",
            f"avg total tokens: {token_stats.get('mean', 'n/a')}",
            f"avg completion tok/s: {throughput_stats.get('mean', 'n/a')}",
        ]
        ax.set_title("Run Summary")
        ax.text(
            0.05,
            0.95,
            "\n".join(summary_lines),
            ha="left",
            va="top",
            transform=ax.transAxes,
            fontsize=11,
        )
        ax.set_xticks([])
        ax.set_yticks([])

        fig.tight_layout(rect=[0, 0, 1, 0.96])
        fig.savefig(png_path, dpi=160, bbox_inches="tight")
        plt.close(fig)
        return None

    def summarise_artifact(self, artifact: Path) -> Path | None:
        question_metrics = self.collect_artifact_metrics(artifact)
        if not question_metrics:
            print(f"[LLM] No question audits found: {artifact.name}")
            return None

        summary_dir = artifact / "metrics_summaries"
        summary_dir.mkdir(parents=True, exist_ok=True)
        json_path = summary_dir / SUMMARY_FILENAME
        png_path = summary_dir / SUMMARY_PNG_FILENAME

        answer_sources = Counter(
            metric["outcome"].get("answer_source") or "unknown"
            for metric in question_metrics
        )
        model_counts = Counter(
            metric.get("model") or "unknown"
            for metric in question_metrics
        )
        structured_ready = sum(
            1 for metric in question_metrics if metric["outcome"].get("structured_context_ready") is True
        )
        structured_unavailable = sum(
            1 for metric in question_metrics if metric["outcome"].get("structured_context_ready") is not True
        )
        audio_generated = sum(
            1 for metric in question_metrics if metric["outcome"].get("audio_generated") is True
        )
        llm_errors = sum(
            1 for metric in question_metrics if metric["outcome"].get("llm_error_type")
        )

        try:
            graph_error = self.save_graphical_summary(
                png_path=png_path,
                artifact_name=artifact.name,
                question_metrics=question_metrics,
            )
        except Exception as error:
            graph_error = f"graph generation failed: {error}"

        summary = {
            "artifact": artifact.name,
            "generated_at": utc_now_iso(),
            "question_count": len(question_metrics),
            "aggregate_metrics": {
                "pipeline_wall_ms": numeric_stats(
                    [metric["latency_ms"].get("pipeline_wall") for metric in question_metrics]
                ),
                "llm_wall_ms": numeric_stats(
                    [metric["latency_ms"].get("llm_wall") for metric in question_metrics]
                ),
                "ollama_total_ms": numeric_stats(
                    [metric["latency_ms"].get("ollama_total") for metric in question_metrics]
                ),
                "ollama_load_ms": numeric_stats(
                    [metric["latency_ms"].get("ollama_load") for metric in question_metrics]
                ),
                "ollama_prompt_eval_ms": numeric_stats(
                    [metric["latency_ms"].get("ollama_prompt_eval") for metric in question_metrics]
                ),
                "ollama_completion_eval_ms": numeric_stats(
                    [metric["latency_ms"].get("ollama_completion_eval") for metric in question_metrics]
                ),
                "model_context_wait_ms": numeric_stats(
                    [metric["latency_ms"].get("model_context_wait") for metric in question_metrics]
                ),
                "prompt_tokens": numeric_stats(
                    [metric["tokens"].get("prompt") for metric in question_metrics]
                ),
                "completion_tokens": numeric_stats(
                    [metric["tokens"].get("completion") for metric in question_metrics]
                ),
                "total_tokens": numeric_stats(
                    [metric["tokens"].get("total") for metric in question_metrics]
                ),
                "completion_tokens_per_second": numeric_stats(
                    [
                        metric["tokens"].get("completion_tokens_per_second")
                        for metric in question_metrics
                    ]
                ),
                "question_chars": numeric_stats(
                    [metric["chars"].get("question") for metric in question_metrics]
                ),
                "context_chars": numeric_stats(
                    [metric["chars"].get("context") for metric in question_metrics]
                ),
                "vlm_chars": numeric_stats(
                    [metric["chars"].get("vlm") for metric in question_metrics]
                ),
                "answer_chars": numeric_stats(
                    [metric["chars"].get("answer") for metric in question_metrics]
                ),
            },
            "outcome_counts": {
                "answer_sources": dict(answer_sources),
                "models": dict(model_counts),
                "structured_context_ready": structured_ready,
                "structured_context_unavailable": structured_unavailable,
                "audio_generated": audio_generated,
                "audio_unavailable": len(question_metrics) - audio_generated,
                "llm_errors": llm_errors,
            },
            "question_metrics": question_metrics,
            "graphical_summary_png": png_path.name if graph_error is None else None,
        }
        if graph_error is not None:
            summary["graphical_summary_error"] = graph_error

        json_path.write_text(json.dumps(summary, indent=2) + "\n")
        if graph_error is None:
            print(f"[LLM] Wrote {json_path.name} and {png_path.name}")
        else:
            print(f"[LLM] Wrote {json_path.name}; graph skipped ({graph_error})")
        return json_path

    def run_once(self, *, artifact: str | None = None, latest: bool = False) -> int:
        if artifact is not None:
            artifacts = [self.resolve_artifact(artifact)]
        elif latest:
            latest_artifact = self.latest_artifact_with_audits()
            if latest_artifact is None:
                print(f"[LLM] No question audits found under: {self.frames_root}")
                return 0
            artifacts = [latest_artifact]
        else:
            artifacts = self.get_artifacts()

        if not artifacts:
            print(f"[LLM] No session artifacts found: {self.frames_root}")
            return 0

        for artifact_path in artifacts:
            if not artifact_path.exists():
                print(f"[LLM] Artifact not found: {artifact_path}")
                continue
            self.summarise_artifact(artifact_path)

        return 0

    def run(self, *, artifact: str | None = None) -> int:
        print("[LLM] Watching question audits...")
        while True:
            artifacts = [self.resolve_artifact(artifact)] if artifact is not None else self.get_artifacts()
            if not artifacts:
                print("[LLM] Waiting for a session to start...")
                time.sleep(self.interval)
                continue

            for artifact_path in artifacts:
                try:
                    if not artifact_path.exists() or self.summary_is_current(artifact_path):
                        continue
                    self.summarise_artifact(artifact_path)
                except Exception as error:
                    print(f"[LLM] Failed {artifact_path.name}: {error}")

            time.sleep(self.interval)


def _parse_args():
    parser = argparse.ArgumentParser(description="Summarise LLM question latency and token usage from session artifacts.")
    parser.add_argument(
        "--artifacts",
        default=str(APP_DIR / "session_artifacts"),
        help="Session artifacts root directory",
    )
    parser.add_argument(
        "--artifact",
        help="Specific artifact name or path to summarise",
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Summarise the latest artifact that has question audits",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Keep watching artifacts and refresh summaries as questions finish",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Watch polling interval in seconds",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    runner = LlmQuestionSummaryRunner(
        frames_root=args.artifacts,
        interval=args.interval,
    )
    if args.watch:
        raise SystemExit(runner.run(artifact=args.artifact))
    raise SystemExit(runner.run_once(artifact=args.artifact, latest=args.latest))
