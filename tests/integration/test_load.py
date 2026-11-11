#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/18 17:29:43.383581
Revised: 2026/11/11 17:42:29.053514

Load test: drives a short headless locust run (tests/load/locustfile.py)
against a live_server and asserts the backend survived it — zero failed
requests, and a 95th-percentile response time budget generous enough to
absorb CI/dev-machine noise while still catching an actual regression
(e.g. a missing index turning a query pathological under concurrency).

Not a benchmark suite: this asserts "still works under a burst of
concurrent traffic," not a tracked performance number over time.
"""

import csv
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.load]

_LOCUSTFILE = Path(__file__).resolve().parents[1] / "load" / "locustfile.py"
_P95_BUDGET_MS = 3000


def test_backend_survives_a_short_burst_of_concurrent_load(live_server):
    with tempfile.TemporaryDirectory() as tmp:
        csv_prefix = Path(tmp) / "load"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "locust",
                "-f",
                str(_LOCUSTFILE),
                "--host",
                live_server,
                "--headless",
                "-u",
                "20",
                "-r",
                "10",
                "-t",
                "15s",
                "--csv",
                str(csv_prefix),
                "--only-summary",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        stats_file = Path(f"{csv_prefix}_stats.csv")
        if not stats_file.exists():
            pytest.fail(f"locust produced no stats file:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")

        rows = list(csv.DictReader(stats_file.read_text(encoding="utf-8").splitlines()))
        aggregated = next(r for r in rows if r["Name"] == "Aggregated")
        failure_count = int(aggregated["Failure Count"])
        if int(aggregated["Request Count"]) == 0:  # locust writes "N/A" percentiles then
            pytest.fail(f"locust sent no requests:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        p95 = float(aggregated["95%"])

        assert failure_count == 0, f"{failure_count} failed requests under load:\n{result.stdout}"
        assert p95 < _P95_BUDGET_MS, f"95th percentile response time {p95:.0f}ms exceeds the {_P95_BUDGET_MS}ms budget"
