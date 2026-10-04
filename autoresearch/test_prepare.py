import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import prepare


class FakeCompletions:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)

    def create(self, **_kwargs):
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class EvaluationRetryTests(unittest.TestCase):
    def test_exhausted_5xx_row_is_tracked_and_skipped(self):
        server_error = RuntimeError("server error")
        server_error.status_code = 500
        success = SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(content="A short summary."),
        )])
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=FakeCompletions([server_error] * 4 + [success]))
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            eval_file = root / "eval.jsonl"
            rows = [
                {"id": "failed", "article": "Article one", "reference": "Reference one"},
                {"id": "success", "article": "Article two", "reference": "A short summary."},
            ]
            eval_file.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            appended = []

            with patch.object(prepare, "RUNS", root / "runs"), \
                    patch.object(prepare, "EVAL_FILE", eval_file), \
                    patch.object(prepare, "client", return_value=fake_client), \
                    patch.object(prepare, "retryable_eval_error", side_effect=lambda exc: ("server_error", exc.status_code)), \
                    patch.object(prepare, "append_result", side_effect=appended.append), \
                    patch.object(prepare, "plot_results"), \
                    patch.object(prepare.time, "sleep"):
                run_id = prepare.score_deployment("deployment", "base", description="test")

            metrics = json.loads((root / "runs" / run_id / "metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(metrics["eval_count"], 1)
            self.assertEqual(metrics["eval_total"], 2)
            self.assertEqual(metrics["eval_failure_count"], 1)
            self.assertEqual(metrics["server_error_retry_count"], 3)
            self.assertEqual(appended[0]["eval_count"], 2)

            predictions = [
                json.loads(line)
                for line in (root / "runs" / run_id / "predictions.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(predictions[0]["error"], "server_error")
            self.assertEqual(predictions[0]["attempts"], 4)
            self.assertIsNotNone(predictions[1]["rouge_l"])

    def test_timeout_is_retried(self):
        timeout = RuntimeError("timed out")
        success = SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(content="A short summary."),
        )])
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=FakeCompletions([timeout, success]))
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            eval_file = root / "eval.jsonl"
            eval_file.write_text(json.dumps({
                "id": "row", "article": "Article", "reference": "A short summary."
            }) + "\n", encoding="utf-8")

            with patch.object(prepare, "RUNS", root / "runs"), \
                    patch.object(prepare, "EVAL_FILE", eval_file), \
                    patch.object(prepare, "client", return_value=fake_client), \
                    patch.object(prepare, "retryable_eval_error", return_value=("timeout", None)), \
                    patch.object(prepare, "append_result"), \
                    patch.object(prepare, "plot_results"), \
                    patch.object(prepare.time, "sleep"):
                run_id = prepare.score_deployment("deployment", "base", description="test")

            metrics = json.loads((root / "runs" / run_id / "metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(metrics["eval_count"], 1)
            self.assertEqual(metrics["eval_failure_count"], 0)
            self.assertEqual(metrics["server_error_retries"][0]["error_type"], "timeout")

    def test_report_shows_successful_rows_out_of_total(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id = "sft-test"
            run_dir = root / "runs" / run_id
            run_dir.mkdir(parents=True)
            (run_dir / "metrics.json").write_text(
                json.dumps({"eval_count": 97, "eval_total": 100}), encoding="utf-8"
            )
            report = root / "results.md"
            row = {
                "run_id": run_id, "model_id": "model", "kind": "sft", "n_epochs": "2",
                "learning_rate_multiplier": "1.0", "batch_size": "1", "rouge_l": "0.2",
                "delta_vs_base": "0.1", "eval_count": "100", "description": "test",
                "status": "completed",
            }
            with patch.object(prepare, "RUNS", root / "runs"), patch.object(prepare, "RESULTS_REPORT_FILE", report):
                prepare.write_results_report([row])

            self.assertIn("| **97/100** |", report.read_text(encoding="utf-8"))

    def test_report_uses_historical_scored_count_without_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "results.md"
            row = {
                "run_id": "historical", "model_id": "model", "kind": "sft", "n_epochs": "2",
                "learning_rate_multiplier": "0.1", "batch_size": "auto", "rouge_l": "0.2",
                "delta_vs_base": "0.1", "eval_count": "100",
                "description": "Completed; 93 scored and 7 content-filtered rows", "status": "completed",
            }
            with patch.object(prepare, "RUNS", root / "runs"), patch.object(prepare, "RESULTS_REPORT_FILE", report):
                prepare.write_results_report([row])

            self.assertIn("| **93/100** |", report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
