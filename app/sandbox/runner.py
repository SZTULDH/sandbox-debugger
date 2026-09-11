"""沙盒评测执行：函数级 / 类级测试套件。

一个套件一个子进程；harness 增量落盘保留逐用例归因。
类级默认共享同一实例（顺序调用 method），单测可 reset=true 重建。
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HARNESS_PATH = Path(__file__).with_name("_harness.py")
STARTUP_OVERHEAD = 5.0
DEBUG = bool(os.getenv("SANDBOX_DEBUG"))
DEFAULT_TIMEOUT = float(os.getenv("SANDBOX_TIMEOUT", "5"))
MAX_OUTPUT = int(os.getenv("SANDBOX_MAX_OUTPUT_CHARS", "20000"))
RECURSION_LIMIT = int(os.getenv("SANDBOX_RECURSION_LIMIT", "3000"))


@dataclass
class TestResult:
    index: int
    args: list
    expected: Any
    status: str
    actual: Any = None
    error: str = ""
    traceback: str = ""
    stdout: str = ""
    stderr: str = ""
    duration_ms: float = 0.0
    method: str | None = None

    @property
    def passed(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict:
        d = {
            "index": self.index,
            "args": self.args,
            "expected": self.expected,
            "status": self.status,
            "actual": self.actual,
            "error": self.error[:300],
            "duration_ms": round(self.duration_ms, 3),
        }
        if self.method:
            d["method"] = self.method
        if self.status == "ok":
            return d
        lim = 100000 if DEBUG else 600
        if self.traceback:
            d["traceback"] = self.traceback[-lim:]
        if self.stdout:
            d["stdout"] = self.stdout[-lim:]
        if self.stderr:
            d["stderr"] = self.stderr[-lim:]
        return d


@dataclass
class SuiteResult:
    results: list[TestResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def all_passed(self) -> bool:
        return self.total > 0 and self.failed == 0

    def failure_samples(self, limit: int = 2) -> list[dict]:
        return [r.to_dict() for r in self.results if not r.passed][:limit]

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "all_passed": self.all_passed,
            "failure_samples": self.failure_samples(),
        }


def values_equal(actual: Any, expected: Any) -> bool:
    if isinstance(expected, bool) or isinstance(actual, bool):
        if isinstance(expected, bool) and isinstance(actual, bool):
            return actual == expected
        return False
    if isinstance(expected, float) or isinstance(actual, float):
        try:
            return math.isclose(float(actual), float(expected), rel_tol=1e-9, abs_tol=1e-9)
        except (TypeError, ValueError):
            return False
    if isinstance(expected, dict) and isinstance(actual, dict):
        if set(expected.keys()) != set(actual.keys()):
            return False
        return all(values_equal(actual[k], expected[k]) for k in expected)
    if isinstance(expected, (list, tuple)) and isinstance(actual, (list, tuple)):
        if len(expected) != len(actual):
            return False
        return all(values_equal(a, e) for a, e in zip(actual, expected))
    return actual == expected


def run_suite(
    code: str,
    entry_point: str,
    tests: list[dict],
    *,
    kind: str = "function",
    class_name: str | None = None,
    init_args: list | None = None,
    init_kwargs: dict | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> SuiteResult:
    """执行测试套件。

    kind="function": 调 entry_point(*args)
    kind="class": 构造 class_name(*init_args, **init_kwargs)，
                  再按用例 method（默认 entry_point）调用；同实例顺序执行。
    """
    if not tests:
        return SuiteResult()

    with tempfile.TemporaryDirectory(prefix="sbox_") as tmp:
        workdir = Path(tmp)
        code_path = workdir / "candidate.py"
        code_path.write_text(code, encoding="utf-8")

        timeouts = [float(c.get("timeout", timeout)) for c in tests]
        spec_tests = [dict(c, timeout=t) for c, t in zip(tests, timeouts)]
        budget = sum(timeouts) + STARTUP_OVERHEAD

        spec = {
            "code_path": str(code_path),
            "kind": kind,
            "entry_point": entry_point,
            "class_name": class_name or entry_point,
            "init_args": init_args or [],
            "init_kwargs": init_kwargs or {},
            "tests": spec_tests,
            "max_output_chars": MAX_OUTPUT,
            "recursion_limit": RECURSION_LIMIT,
        }
        spec_path = workdir / "spec.json"
        spec_path.write_text(
            json.dumps(spec, ensure_ascii=False, default=repr), encoding="utf-8"
        )
        out_path = workdir / "out.json"

        timed_out = False
        start = time.perf_counter()
        returncode: int | None = None
        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(HARNESS_PATH), str(spec_path), str(out_path)],
                capture_output=True,
                timeout=budget,
                cwd=str(workdir),
                stdin=subprocess.DEVNULL,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            returncode = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
        wall_ms = (time.perf_counter() - start) * 1000

        state = _read_state(out_path)
        if state.get("watchdog_timeout") or returncode == 2:
            timed_out = True
        completed = {int(r.get("index", -1)): r for r in state.get("completed", [])}
        hanging = state.get("in_progress")

        suite = SuiteResult()
        for i, case in enumerate(tests):
            expected = case.get("expected")
            args = case.get("args", [])
            method = case.get("method")
            payload = completed.get(i)

            if payload is None:
                status = "timeout" if (timed_out and i == hanging) else "not_run"
                suite.results.append(
                    TestResult(
                        i,
                        args,
                        expected,
                        status,
                        error=(
                            f"超过 {timeouts[i]}s 未返回"
                            if status == "timeout"
                            else "前序用例超时，未执行"
                        ),
                        duration_ms=wall_ms if status == "timeout" else 0.0,
                        method=method,
                    )
                )
                continue

            if payload.get("status") != "ok":
                suite.results.append(
                    TestResult(
                        i,
                        args,
                        expected,
                        payload.get("status", "runtime_error"),
                        error=payload.get("error", ""),
                        traceback=payload.get("traceback", ""),
                        stdout=payload.get("stdout", ""),
                        stderr=payload.get("stderr", ""),
                        duration_ms=float(payload.get("duration_ms", 0.0)),
                        method=payload.get("method") or method,
                    )
                )
                continue

            actual = payload.get("result")
            ok = values_equal(actual, expected)
            suite.results.append(
                TestResult(
                    i,
                    args,
                    expected,
                    "ok" if ok else "wrong_answer",
                    actual=actual,
                    stdout=payload.get("stdout", ""),
                    stderr=payload.get("stderr", ""),
                    duration_ms=float(payload.get("duration_ms", 0.0)),
                    method=payload.get("method") or method,
                )
            )

    return suite


def run_problem(code: str, problem: dict, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """按题目 JSON 跑 public_tests（及可选 adversarial_tests）。"""
    kind = problem.get("kind") or "function"
    entry = problem.get("entry_point") or ""
    public = problem.get("public_tests") or []
    adv = problem.get("adversarial_tests") or []

    def _run(tests: list[dict]) -> SuiteResult:
        return run_suite(
            code,
            entry,
            tests,
            kind=kind,
            class_name=problem.get("class_name"),
            init_args=problem.get("init_args"),
            init_kwargs=problem.get("init_kwargs"),
            timeout=timeout,
        )

    pub = _run(public)
    out = {"public": pub.to_dict()}
    if adv:
        out["adversarial"] = _run(adv).to_dict()
    return out


def _read_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"completed": [], "in_progress": None}


def check_syntax(code: str) -> str | None:
    try:
        compile(code, "<candidate>", "exec")
        return None
    except SyntaxError as exc:
        return f"SyntaxError: {exc.msg} (行 {exc.lineno})"
