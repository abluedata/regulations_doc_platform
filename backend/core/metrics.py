"""Small in-process metrics registry for the local API runtime."""
from __future__ import annotations

from collections import Counter
from threading import Lock


class Metrics:
    def __init__(self):
        self._lock = Lock()
        self._requests = Counter()
        self._duration_ms = Counter()
        self._jobs = Counter()

    def record_request(self, status: int, duration_ms: float) -> None:
        with self._lock:
            self._requests[str(status)] += 1
            self._duration_ms[str(status)] += round(duration_ms, 2)

    def record_job(
        self,
        *,
        status: str,
        duration_ms: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        estimated_cost: float = 0.0,
        error_count: int = 0,
        dead_letter_count: int = 0,
    ) -> None:
        with self._lock:
            self._jobs["total"] += 1
            self._jobs[f"status:{status}"] += 1
            self._jobs["duration_ms_total"] += round(duration_ms, 2)
            self._jobs["prompt_tokens"] += prompt_tokens
            self._jobs["completion_tokens"] += completion_tokens
            self._jobs["estimated_cost"] += estimated_cost
            self._jobs["errors"] += error_count
            self._jobs["dead_letters"] += dead_letter_count

    def snapshot(self) -> dict[str, dict[str, float | int]]:
        with self._lock:
            total_jobs = int(self._jobs["total"])
            failed_jobs = sum(
                count
                for key, count in self._jobs.items()
                if key.startswith("status:") and key.removeprefix("status:") not in {"completed", "complete", "complete_degraded"}
            )
            return {
                "requests_by_status": dict(self._requests),
                "duration_ms_by_status": dict(self._duration_ms),
                "review_jobs": {
                    "total": total_jobs,
                    "by_status": {key.removeprefix("status:"): value for key, value in self._jobs.items() if key.startswith("status:")},
                    "duration_ms_total": round(float(self._jobs["duration_ms_total"]), 2),
                    "prompt_tokens": int(self._jobs["prompt_tokens"]),
                    "completion_tokens": int(self._jobs["completion_tokens"]),
                    "estimated_cost": round(float(self._jobs["estimated_cost"]), 6),
                    "errors": int(self._jobs["errors"]),
                    "dead_letters": int(self._jobs["dead_letters"]),
                    "error_rate": round(failed_jobs / total_jobs, 6) if total_jobs else 0.0,
                },
            }


metrics = Metrics()
