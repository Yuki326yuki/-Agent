from datetime import datetime, timezone
from pathlib import Path
import io
import json
import platform
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
stream = io.StringIO()
result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
log = stream.getvalue()
target = ROOT / "examples"
target.mkdir(exist_ok=True)
(target / "test_results.txt").write_text(log, encoding="utf-8")
summary = {"mode": "offline_mock", "real_model_verified": False, "python_version": platform.python_version(),
           "created_at": datetime.now(timezone.utc).isoformat(), "tests_run": result.testsRun,
           "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
           "successful": result.wasSuccessful()}
(target / "test_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(log)
raise SystemExit(0 if result.wasSuccessful() else 1)
