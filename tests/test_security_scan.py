#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/18 17:25:23.777389
Revised: 2026/08/18 17:25:23.777389

SAST (bandit) and dependency vulnerability (pip-audit) scans, run as real
pytest tests rather than a separate CI step — a developer sees the failure
the same way any other test failure shows up, and it's part of the same
`pytest -m security` a reviewer would run before a release.

Known false positives are suppressed project-wide via [tool.bandit] in
pyproject.toml, not inline — see that section's comment for why (bandit
attributes db_triggers.py's one finding to an f-string's opening line,
where a trailing comment would corrupt the SQL literal it opens). Both
tests fail loudly on genuinely new findings, in either category.

pip-audit needs network access (queries the OSV/PyPI vulnerability
database) — see the `security` marker's exclusion from addopts.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.security

_ROOT = Path(__file__).resolve().parents[1]


def test_bandit_finds_no_issues():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "bandit",
            "-q",
            "-c",
            str(_ROOT / "pyproject.toml"),
            "-r",
            str(_ROOT / "src"),
            "-f",
            "json",
        ],
        capture_output=True,
        text=True,
    )
    if not result.stdout:
        pytest.fail(f"bandit produced no output (exit {result.returncode}):\n{result.stderr}")
    issues = json.loads(result.stdout)["results"]
    assert not issues, "bandit found issues:\n" + "\n".join(
        f"{i['test_id']} {i['issue_severity']} {i['filename']}:{i['line_number']} — {i['issue_text']}" for i in issues
    )


def test_pip_audit_finds_no_known_vulnerabilities():
    result = subprocess.run(
        [sys.executable, "-m", "pip_audit", "--skip-editable", "-f", "json"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
    )
    if not result.stdout:
        pytest.fail(f"pip-audit produced no output (exit {result.returncode}):\n{result.stderr}")
    dependencies = json.loads(result.stdout)["dependencies"]
    vulnerable = [dep for dep in dependencies if dep.get("vulns")]
    assert not vulnerable, "pip-audit found known vulnerabilities:\n" + "\n".join(
        f"{dep['name']} {dep['version']}: {[v['id'] for v in dep['vulns']]}" for dep in vulnerable
    )
