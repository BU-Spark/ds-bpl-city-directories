#!/usr/bin/env python3
"""Run a selected 1916 directory volume assignment with one CPU worker."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
PROJECT = "plans/1916/project.json"
VOLUMES = {
    "vol1": {"project": PROJECT, "config": "config/vol1.json", "pages": 1371,
             "batches": 14, "volume_id": "boston-1916-vol1-ao"},
    "vol2": {"project": "plans/1916/vol2-project.json", "config": "config/vol2.json",
             "pages": 566, "batches": 6, "volume_id": "boston-1916-vol2-oz"},
}


def load_project(volume="vol1"):
    return json.loads((ROOT / VOLUMES[volume]["project"]).read_text(encoding="utf-8"))


def listed_assignment_ids(project):
    return [a["assignment_id"] for a in project["assignments"]]


def verify_package(assignment_id=None, volume="vol1"):
    entries = json.loads((ROOT / "CHECKSUMS.json").read_text(encoding="utf-8"))
    for name, digest in entries.items():
        path = ROOT / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Package file missing or changed: " + name)
    scope = VOLUMES[volume]
    project = load_project(volume)
    ids = listed_assignment_ids(project)
    if not ids:
        raise ValueError("Project has no worker assignments")
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate assignment IDs in project.json")
    if sum(a["pages"] for a in project["assignments"]) != project["total_pages"]:
        raise ValueError("Assignment page counts do not sum to total_pages")
    if (project["total_pages"] != scope["pages"] or
            sum(len(a["batches"]) for a in project["assignments"]) != scope["batches"] or
            any(a["volume_id"] != scope["volume_id"] for a in project["assignments"])):
        raise ValueError("Unexpected " + volume + " scope")
    if assignment_id is None:
        return project, None
    choices = [a for a in project["assignments"] if a["assignment_id"] == assignment_id]
    if len(choices) != 1:
        raise ValueError(
            f"Unknown assignment ID {assignment_id!r}. Available: {', '.join(ids)}")
    return project, choices[0]


def invoke(arguments, environment, log_path):
    process = subprocess.Popen([sys.executable, "-u", "-m", "bpl_ocr", *arguments], cwd=ROOT,
                               env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace", start_new_session=True)
    try:
        with log_path.open("a", encoding="utf-8") as log:
            for line in process.stdout:
                print(line, end="", flush=True)
                log.write(line)
                log.flush()
        return process.wait()
    except KeyboardInterrupt:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                print("The worker is still stopping; inspect its checkpoint before restarting.", file=sys.stderr)
        return 130


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--volume", choices=tuple(VOLUMES), default="vol1",
                        help="Volume to run; defaults to vol1 for existing worker commands")
    parser.add_argument("--assignment",
                        help="Assignment ID for the selected volume; use --list-assignments")
    parser.add_argument("--list-assignments", action="store_true",
                        help="List configured worker assignments and exit")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "results",
                        help="Persistent result root; reuse the same path to resume")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="Verify package/assignment without OCR/dependencies")
    mode.add_argument("--check", action="store_true",
                      help="Verify engine and download/check pinned English weights without OCR")
    mode.add_argument("--status", action="store_true", help="Read local coverage without OCR")
    parser.add_argument("--max-batches", type=int,
                        help="Process only this many additional unfinished batches")
    args = parser.parse_args()
    if args.max_batches is not None and args.max_batches < 1:
        parser.error("--max-batches must be positive")

    if args.list_assignments:
        project, _ = verify_package(volume=args.volume)
        for assignment in project["assignments"]:
            batches = ", ".join(b["batch_id"] for b in assignment["batches"])
            print(f"{assignment['assignment_id']}: owner={assignment['owner']} "
                  f"pages={assignment['pages']} batches=[{batches}]")
        return 0

    if not args.assignment:
        parser.error("--assignment is required (use --list-assignments to see options)")

    project, assignment = verify_package(args.assignment, volume=args.volume)
    scope = VOLUMES[args.volume]
    data = args.data_dir.expanduser().resolve()
    command = ["run-assignment", "--project", scope["project"], "--assignment", args.assignment,
               "--data-dir", str(data)]
    if args.max_batches is not None:
        command += ["--max-batches", str(args.max_batches)]
    if args.dry_run:
        print(json.dumps({
            "package": "verified",
            "owner": assignment["owner"],
            "assignment_id": args.assignment,
            "available_assignments": listed_assignment_ids(project),
            "volume": assignment["volume_id"],
            "project": scope["project"],
            "physical_pages": assignment["pages"],
            "batches": len(assignment["batches"]),
            "batch_ids": [b["batch_id"] for b in assignment["batches"]],
            "data_directory": str(data / args.assignment),
            "command": shlex.join([sys.executable, "-m", "bpl_ocr", *command]),
            "ocr_started": False,
        }, indent=2))
        return 0
    if os.name != "posix":
        raise RuntimeError("On Windows, run this package inside WSL2 with a Linux Conda environment")
    environment = {**os.environ, "OMP_THREAD_LIMIT": "1"}
    folder = data / args.assignment
    folder.mkdir(parents=True, exist_ok=True)
    log = folder / "runner.log"
    if args.status:
        return invoke(["assignment-status", "--project", scope["project"], "--assignment", args.assignment,
                       "--data-dir", str(data)], environment, log)
    checked = invoke(["doctor", "--config", scope["config"], "--work-dir", str(folder / "work")],
                     environment, log)
    if checked or args.check:
        return checked
    return invoke(command, environment, log)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(type(error).__name__ + ": " + str(error), file=sys.stderr)
        raise SystemExit(1)
