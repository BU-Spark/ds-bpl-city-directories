#!/usr/bin/env python3
"""Validate four fixed Volume-2 pages in a separate, resumable data directory."""

import argparse
import json
import os
from pathlib import Path
import sys

from run_ocr import ROOT, verify_package

PLAN = "plans/1916/validation/vol2-preflight.json"
MANIFEST = "manifests/vol2/manifest.json"
LEAVES = [7, 288, 571, 572]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Verify package and fixed sample; no OCR")
    mode.add_argument("--status", action="store_true", help="Read the saved validation summary; no OCR")
    mode.add_argument("--run", action="store_true", help="Recognize/resume only the four validation pages")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "results/validation-vol2",
                        help="Validation directory; reuse this path when resuming")
    parser.add_argument("--max-pages", type=int, help="Stop after this many additional pages")
    args = parser.parse_args(argv)
    if args.max_pages is not None and (not args.run or args.max_pages < 1):
        parser.error("--max-pages must be positive and used with --run")
    verify_package("worker-vol2", volume="vol2")
    plan = json.loads((ROOT / PLAN).read_text(encoding="utf-8"))
    if plan["leaves"] != LEAVES:
        raise ValueError("Validation must contain only leaves 7, 288, 571 and 572")
    data = args.data_dir.expanduser().resolve()
    if data.name == "worker-vol2" or (data / "assignment.json").exists():
        raise ValueError("Use a separate validation directory, outside the production assignment")
    if args.dry_run:
        result = {"package": "verified", "kind": "bounded_validation", "leaves": LEAVES,
                  "physical_pages": len(LEAVES), "data_directory": str(data),
                  "plan": PLAN, "ocr_started": False, "production_queue_started": False}
    elif args.status:
        summary = data / "batch/summary.json"
        result = (json.loads(summary.read_text(encoding="utf-8")) if summary.exists()
                  else {"status": "not_started", "planned_pages": len(LEAVES)})
    else:
        os.environ["OMP_THREAD_LIMIT"] = "1"
        import bpl_ocr
        from bpl_ocr.batch import run_batch
        if Path(bpl_ocr.__file__).resolve().parent != (ROOT / "src/bpl_ocr").resolve():
            raise RuntimeError("Install this checkout with python -m pip install -e ./fa26/ocr")
        result = run_batch(ROOT / MANIFEST, ROOT / PLAN, data / "work", data / "batch",
                           max_pages=args.max_pages)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 2 if result.get("status") == "needs_attention" else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted. Resume with the same validation directory.", file=sys.stderr)
        raise SystemExit(130)
    except (OSError, ValueError, RuntimeError) as error:
        print(type(error).__name__ + ": " + str(error), file=sys.stderr)
        raise SystemExit(1)
