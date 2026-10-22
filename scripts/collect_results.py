"""Run the test suites and record measured results for the lab file:  python scripts/collect_results.py
Writes docs/lab-file/results.json (read by docs/lab-file/build_lab_file.py). Nothing here is hand-edited."""
from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "lab-file" / "results.json"


def run(cmd: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def loc(paths: list[str], exts: tuple[str, ...]) -> int:
    n = 0
    for base in paths:
        for f in (ROOT / base).rglob("*"):
            if f.is_file() and f.suffix in exts and "node_modules" not in f.parts and "dist" not in f.parts and "__pycache__" not in f.parts and ".venv" not in f.parts:
                n += sum(1 for line in f.read_text(encoding="utf8", errors="ignore").splitlines() if line.strip())
    return n


def measure_latency(n: int = 300) -> dict:
    """In-process latency of POST /api/transactions (ASGI, SQLite on local disk). Excludes network and browser time."""
    import os
    import tempfile
    import time
    tmpdir = Path(tempfile.mkdtemp(prefix="fraud-latency-"))
    os.environ["FRAUD_DB"] = str(tmpdir / "import.sqlite")
    sys.path.insert(0, str(ROOT))
    from fastapi.testclient import TestClient
    from app.core.config import Settings
    from app.main import create_app
    s = Settings(db_path=tmpdir / "lat.sqlite", auth_required=False, seed_demo=False, secret_key="x" * 40, frontend_dist=tmpdir / "none")
    times = []
    with TestClient(create_app(s)) as c:
        for i in range(n):
            body = {"card_token": f"SYNTH-LAT-{i % 50:04d}", "amount": 500 + i, "merchant": "Swiggy", "channel": "ONLINE", "location": "Delhi"}
            t0 = time.perf_counter()
            r = c.post("/api/transactions", json=body)
            times.append((time.perf_counter() - t0) * 1000)
            assert r.status_code == 200
    times.sort()
    q = lambda f: round(times[min(int(f * len(times)), len(times) - 1)], 1)  # noqa: E731
    return {"n": n, "p50": q(0.50), "p95": q(0.95), "p99": q(0.99), "max": round(times[-1], 1), "note": "in-process, excludes network"}


def main() -> int:
    tmp = ROOT / ".results-tmp"
    tmp.mkdir(exist_ok=True)
    py = run([sys.executable, "-m", "pytest", "-q", "--cov=app", "--cov=ml.wrapper", f"--cov-report=json:{tmp / 'cov.json'}", f"--junitxml={tmp / 'junit.xml'}"])
    root = ET.parse(tmp / "junit.xml").getroot()
    suite = root if root.tag == "testsuite" else root[0]
    cov = json.loads((tmp / "cov.json").read_text())
    files = {k: {"statements": v["summary"]["num_statements"], "missing": v["summary"]["missing_lines"], "percent": round(v["summary"]["percent_covered"], 1)} for k, v in cov["files"].items()}
    backend = {"tests": int(suite.get("tests")), "failures": int(suite.get("failures")) + int(suite.get("errors")), "skipped": int(suite.get("skipped")), "seconds": float(suite.get("time")),
               "coverage_percent": round(cov["totals"]["percent_covered"], 1), "statements": cov["totals"]["num_statements"], "files": files,
               "modules": {}}
    for case in suite.iter("testcase"):
        backend["modules"].setdefault(case.get("classname", "").split(".")[1] if "." in case.get("classname", "") else case.get("classname", ""), 0)
        backend["modules"][case.get("classname", "").split(".")[1] if "." in case.get("classname", "") else case.get("classname", "")] += 1
    fe = {"tests": None}
    vt = run(["npx", "vitest", "run", "--reporter=json", f"--outputFile={tmp / 'vitest.json'}"], ROOT / "frontend")
    if (tmp / "vitest.json").exists():
        j = json.loads((tmp / "vitest.json").read_text())
        fe = {"tests": j["numTotalTests"], "passed": j["numPassedTests"], "failed": j["numFailedTests"], "files": j["numTotalTestSuites"] and len(j["testResults"])}
    tsc = run(["npx", "tsc", "--noEmit"], ROOT / "frontend")
    result = {
        "collected_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "python": sys.version.split()[0], "backend": backend, "frontend": fe,
        "typecheck_ok": tsc.returncode == 0, "pytest_exit": py.returncode,
        "loc": {"python_app": loc(["app", "ml"], (".py",)), "python_tests": loc(["tests"], (".py",)), "frontend_src": loc(["frontend/src"], (".ts", ".tsx", ".css"))},
        "latency_ms": measure_latency(),
        "pytest_tail": "\n".join(py.stdout.strip().splitlines()[-3:]),
    }
    OUT.write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "backend"}, indent=2))
    print("backend:", backend["tests"], "tests,", backend["failures"], "failures,", backend["coverage_percent"], "% coverage")
    return 0 if py.returncode == 0 and backend["failures"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
