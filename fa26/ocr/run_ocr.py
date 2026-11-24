#!/usr/bin/env python3
"""Run the fixed volume-1 OCR queue with one CPU worker."""

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
ASSIGNMENT = "worker-vol1"
PROJECT = "plans/1916/project.json"


def verify_package():
    entries = json.loads((ROOT / "CHECKSUMS.json").read_text(encoding="utf-8"))
    for name, digest in entries.items():
        path = ROOT / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Package file missing or changed: " + name)
    project = json.loads((ROOT / PROJECT).read_text(encoding="utf-8"))
    if [a["assignment_id"] for a in project["assignments"]] != [ASSIGNMENT]:
        raise ValueError("This package must contain only the volume-1 assignment")
    assignment = project["assignments"][0]
    if assignment["pages"] != 1371 or len(assignment["batches"]) != 14:
        raise ValueError("Unexpected volume-1 scope")
    return assignment


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
    parser.add_argument("--data-dir", type=Path, default=ROOT / "results", help="Persistent result root; reuse the same path to resume")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Verify bundle and display assignment without OCR/dependencies")
    mode.add_argument("--check", action="store_true", help="Verify engine and download/check pinned English weights without OCR")
    mode.add_argument("--status", action="store_true", help="Read local coverage without OCR")
    parser.add_argument("--max-batches", type=int, help="Process only this many additional unfinished batches")
    args = parser.parse_args()
    if args.max_batches is not None and args.max_batches < 1:
        parser.error("--max-batches must be positive")
    assignment = verify_package()
    data = args.data_dir.expanduser().resolve()
    command = ["run-assignment", "--project", PROJECT, "--assignment", ASSIGNMENT, "--data-dir", str(data)]
    if args.max_batches is not None:
        command += ["--max-batches", str(args.max_batches)]
    if args.dry_run:
        print(json.dumps({"package": "verified", "owner": assignment["owner"], "assignment_id": ASSIGNMENT,
                          "volume": assignment["volume_id"], "physical_pages": assignment["pages"],
                          "batches": len(assignment["batches"]), "data_directory": str(data),
                          "command": shlex.join([sys.executable, "-m", "bpl_ocr", *command]),
                          "ocr_started": False}, indent=2))
        return 0
    if os.name != "posix":
        raise RuntimeError("On Windows, run this package inside WSL2 with a Linux Conda environment")
    environment = {**os.environ, "OMP_THREAD_LIMIT": "1"}
    folder = data / ASSIGNMENT
    folder.mkdir(parents=True, exist_ok=True)
    log = folder / "runner.log"
    if args.status:
        return invoke(["assignment-status", "--project", PROJECT, "--assignment", ASSIGNMENT,
                       "--data-dir", str(data)], environment, log)
    checked = invoke(["doctor", "--config", "config/vol1.json", "--work-dir", str(folder / "work")], environment, log)
    if checked or args.check:
        return checked
    return invoke(command, environment, log)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(type(error).__name__ + ": " + str(error), file=sys.stderr)
        raise SystemExit(1)
