"""Portable command-line entry point; every recognition request is one leaf."""

import argparse
import json
from pathlib import Path
import sys

from .engine import inspect_engine, prepare_model
from .io import load_config
from .manifest import prepare_manifest
from .pipeline import recognize_page


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    manifest = commands.add_parser("manifest", help="Build page/source scope from small IA metadata snapshots")
    manifest.add_argument("--config", type=Path, required=True)
    manifest.add_argument("--output", type=Path, required=True)
    mode = manifest.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="Use checked-in snapshots only")
    mode.add_argument("--refresh", action="store_true", help="Re-fetch source metadata before rebuilding")
    doctor = commands.add_parser("doctor", help="Check pinned engine/Pillow and prepare verified English weights")
    doctor.add_argument("--config", type=Path, required=True)
    doctor.add_argument("--work-dir", type=Path, required=True)
    doctor.add_argument("--tesseract", help="Explicit Tesseract executable, if outside the active environment")
    page = commands.add_parser("ocr-page", help="Download and recognize exactly one in-scope scanned leaf")
    page.add_argument("--manifest", type=Path, required=True)
    page.add_argument("--leaf", type=int, required=True, help="Scandata leafNum, not a printed page or BookReader n-index")
    page.add_argument("--work-dir", type=Path, required=True)
    page.add_argument("--tesseract")
    page.add_argument("--timeout", type=float, default=300, help="Engine timeout in seconds")
    args = parser.parse_args(argv)
    try:
        if args.command == "manifest":
            report = prepare_manifest(args.config, args.output, refresh=args.refresh, offline=args.offline)
            result = {k: report[k] for k in ("manifest_id", "scanned_leaves", "access_pages", "ocr_roles", "absent_primary_printed_labels")}
        elif args.command == "doctor":
            config = load_config(args.config)
            info = inspect_engine(config, args.tesseract)
            model = prepare_model(config, args.work_dir)
            result = {"status": "ready", "tesseract_version": info["version"],
                      "pillow_version": info["pillow_version"], "model_directory": str(model),
                      "english_sha256": config["ocr"]["english_sha256"]}
        else:
            folder, record = recognize_page(args.manifest, args.leaf, args.work_dir,
                                            executable=args.tesseract, timeout=args.timeout)
            result = {"status": record["status"], "printed_page": record["page"]["printed_page"],
                      "leaf_num": args.leaf, "detected_lines": record["detected_lines"],
                      "engine_s": round(record["durations_s"]["engine"], 3), "run_directory": str(folder)}
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except KeyboardInterrupt:
        print("Interrupted. Any completed run and the current failure record are retained.", file=sys.stderr)
        return 130
    except Exception as error:
        print(type(error).__name__ + ": " + str(error), file=sys.stderr)
        return 1
