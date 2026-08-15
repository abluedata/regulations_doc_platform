from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from core.metrics import Metrics
from services.review.job_runner import (
    CapacityExceeded,
    CapacityGovernor,
    ChunkRuleTask,
    ReviewJobRunner,
    TransientReviewError,
)


class CapacityGovernanceTests(unittest.TestCase):
    def test_backpressure_enforces_concurrency_and_queue_limits(self):
        governor = CapacityGovernor(max_concurrent=1, max_queued=1, rate_limit=10, rate_window_seconds=60)

        first = governor.admit("job-1", now=0)
        second = governor.admit("job-2", now=0)

        self.assertEqual(first, "running")
        self.assertEqual(second, "queued")
        with self.assertRaisesRegex(CapacityExceeded, "queue capacity"):
            governor.admit("job-3", now=0)

        self.assertEqual(governor.complete("job-1"), "job-2")
        self.assertEqual(governor.snapshot(), {"running": 1, "queued": 0, "max_concurrent": 1, "max_queued": 1})

    def test_rate_limit_rejects_bursts_and_recovers_after_window(self):
        governor = CapacityGovernor(max_concurrent=2, max_queued=2, rate_limit=2, rate_window_seconds=10)
        governor.admit("job-1", now=0)
        governor.admit("job-2", now=1)

        with self.assertRaisesRegex(CapacityExceeded, "rate limit"):
            governor.admit("job-3", now=2)

        governor.complete("job-1")
        self.assertEqual(governor.admit("job-3", now=11), "running")


class ObservabilityTests(unittest.TestCase):
    def test_job_metrics_capture_latency_tokens_cost_errors_and_dead_letters(self):
        registry = Metrics()
        registry.record_job(
            status="partial_failed",
            duration_ms=125.5,
            prompt_tokens=1000,
            completion_tokens=500,
            estimated_cost=0.0125,
            error_count=2,
            dead_letter_count=1,
        )

        jobs = registry.snapshot()["review_jobs"]
        self.assertEqual(jobs["total"], 1)
        self.assertEqual(jobs["by_status"], {"partial_failed": 1})
        self.assertEqual(jobs["duration_ms_total"], 125.5)
        self.assertEqual(jobs["prompt_tokens"], 1000)
        self.assertEqual(jobs["completion_tokens"], 500)
        self.assertEqual(jobs["estimated_cost"], 0.0125)
        self.assertEqual(jobs["errors"], 2)
        self.assertEqual(jobs["dead_letters"], 1)
        self.assertEqual(jobs["error_rate"], 1.0)

    def test_metrics_endpoint_exposes_only_aggregated_runtime_data(self):
        from api.main import health_metrics

        payload = health_metrics()

        self.assertIn("requests_by_status", payload)
        self.assertIn("review_jobs", payload)
        self.assertNotIn("api_key", str(payload).lower())

    def test_runner_records_dead_letters_and_errors(self):
        registry = Metrics()
        runner = ReviewJobRunner(metrics_registry=registry, sleeper=lambda _seconds: None, max_retries=0)
        task = ChunkRuleTask(job_id="job-1", document_id="doc-1", chunk_id="chunk-1", rule_id="rule-1")

        def fail(_task):
            raise TransientReviewError("provider unavailable")

        runner.run_tasks("job-1", [task], fail)

        jobs = registry.snapshot()["review_jobs"]
        self.assertEqual(jobs["total"], 1)
        self.assertEqual(jobs["errors"], 1)
        self.assertEqual(jobs["dead_letters"], 1)


if __name__ == "__main__":
    unittest.main()
