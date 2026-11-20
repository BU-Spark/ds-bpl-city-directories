"""Traceable page capture, bounded batching and offline quality review."""

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
    review = commands.add_parser("review", help="Verify saved pilot runs and export offline quality flags; no OCR or text edits")
    review.add_argument("--runs", type=Path, required=True, help="Pilot run index accounting for the fixed selection")
    review.add_argument("--manifest", type=Path, required=True)
    review.add_argument("--output", type=Path, required=True)
    review.add_argument("--images", action="store_true", help="Also render source review bands and full-page box overviews")
    batch = commands.add_parser("batch", help="Run or resume a fixed 1–100-page plan with verified checkpoints")
    batch.add_argument("--manifest", type=Path, required=True)
    batch.add_argument("--plan", type=Path, required=True)
    batch.add_argument("--work-dir", type=Path, required=True, help="Source/model/native-run storage; keep outside Git")
    batch.add_argument("--batch-dir", type=Path, required=True, help="Checkpoint and derived batch exports; reuse to resume")
    batch.add_argument("--tesseract")
    batch.add_argument("--max-pages", type=int, help="Pause after scheduling this many additional leaves")
    batch_review = commands.add_parser("batch-review", help="Apply current QA to saved batch captures without OCR or checkpoint changes")
    batch_review.add_argument("--manifest", type=Path, required=True)
    batch_review.add_argument("--work-dir", type=Path, required=True)
    batch_review.add_argument("--batch-dir", type=Path, required=True)
    batch_review.add_argument("--output", type=Path, required=True)
    partition = commands.add_parser("partition", help="Build disjoint volume assignments and 1–100-page plans")
    partition.add_argument("--assign", action="append", required=True, help="OWNER=repo-relative/manifest.json; repeat per volume")
    partition.add_argument("--output", type=Path, required=True)
    partition.add_argument("--batch-size", type=int, default=100)
    assignment = commands.add_parser("run-assignment", help="Run/resume one owner's independent sequential batch queue")
    assignment.add_argument("--project", type=Path, required=True)
    assignment.add_argument("--assignment", required=True)
    assignment.add_argument("--data-dir", type=Path, required=True, help="Machine-local or mounted data root; never commit to Git")
    assignment.add_argument("--max-batches", type=int, help="Stop after this many additional unfinished batches")
    assignment.add_argument("--tesseract")
    status = commands.add_parser("assignment-status", help="Read one owner's local coverage without OCR")
    status.add_argument("--project", type=Path, required=True)
    status.add_argument("--assignment", required=True)
    status.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "partition":
            from .project import partition
            if any("=" not in value for value in args.assign):
                raise ValueError("Each --assign must be OWNER=manifest.json")
            result = partition([value.split("=", 1) for value in args.assign], args.output, batch_size=args.batch_size)
            result = {"project_id": result["project_id"], "total_pages": result["total_pages"],
                      "assignments": [{k: a[k] for k in ("assignment_id", "owner", "pages")} for a in result["assignments"]]}
        elif args.command == "run-assignment":
            from .project import run_assignment
            result = run_assignment(args.project, args.assignment, args.data_dir,
                                    executable=args.tesseract, max_batches=args.max_batches)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 2 if result["status"] == "needs_attention" else 0
        elif args.command == "assignment-status":
            from .project import assignment_status
            result = assignment_status(args.project, args.assignment, args.data_dir)
            result.pop("coverage")
        elif args.command == "manifest":
            report = prepare_manifest(args.config, args.output, refresh=args.refresh, offline=args.offline)
            result = {k: report[k] for k in ("manifest_id", "scanned_leaves", "access_pages", "ocr_roles", "absent_primary_printed_labels")}
        elif args.command == "doctor":
            config = load_config(args.config)
            info = inspect_engine(config, args.tesseract)
            model = prepare_model(config, args.work_dir)
            result = {"status": "ready", "tesseract_version": info["version"],
                      "pillow_version": info["pillow_version"], "model_directory": str(model),
                      "english_sha256": config["ocr"]["english_sha256"]}
        elif args.command == "review":
            from .quality import build_review
            result = build_review(args.runs, args.manifest, args.output)
            if args.images:
                from .quality_images import render_review_images
                result["figures"] = render_review_images(args.runs, args.manifest, args.output)
        elif args.command == "batch":
            from .batch import run_batch
            result = run_batch(args.manifest, args.plan, args.work_dir, args.batch_dir,
                               executable=args.tesseract, max_pages=args.max_pages)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0 if result["status"] in ("completed", "paused") else 2
        elif args.command == "batch-review":
            from .batch import review_batch
            result = review_batch(args.manifest, args.work_dir, args.batch_dir, args.output)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0 if result["status"] == "completed" else 2
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
