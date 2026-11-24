"""Environment check and fixed-assignment OCR runner."""

import argparse
import json
from pathlib import Path
import sys

from .engine import inspect_engine, prepare_model
from .io import load_config


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="Check pinned engine/Pillow and English weights; no OCR")
    doctor.add_argument("--config", type=Path, required=True)
    doctor.add_argument("--work-dir", type=Path, required=True)
    doctor.add_argument("--tesseract")
    run = commands.add_parser("run-assignment", help="Run/resume the fixed assignment")
    run.add_argument("--project", type=Path, required=True)
    run.add_argument("--assignment", required=True)
    run.add_argument("--data-dir", type=Path, required=True)
    run.add_argument("--max-batches", type=int)
    run.add_argument("--tesseract")
    status = commands.add_parser("assignment-status", help="Read local coverage without OCR")
    status.add_argument("--project", type=Path, required=True)
    status.add_argument("--assignment", required=True)
    status.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            config = load_config(args.config)
            info = inspect_engine(config, args.tesseract)
            model = prepare_model(config, args.work_dir)
            result = {"status": "ready", "tesseract_version": info["version"],
                      "pillow_version": info["pillow_version"], "model_directory": str(model),
                      "english_sha256": config["ocr"]["english_sha256"]}
        elif args.command == "assignment-status":
            from .project import assignment_status
            result = assignment_status(args.project, args.assignment, args.data_dir)
            result.pop("coverage")
        else:
            from .project import run_assignment
            result = run_assignment(args.project, args.assignment, args.data_dir,
                                    executable=args.tesseract, max_batches=args.max_batches)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 2 if result.get("status") == "needs_attention" else 0
    except KeyboardInterrupt:
        print("Interrupted. Completed pages and the current attempt are retained.", file=sys.stderr)
        return 130
    except Exception as error:
        print(type(error).__name__ + ": " + str(error), file=sys.stderr)
        return 1
