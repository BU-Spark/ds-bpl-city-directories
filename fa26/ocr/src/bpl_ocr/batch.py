"""Bounded single-worker capture, atomic checkpoints and verified continuation."""

from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import platform
import signal
import socket
import subprocess
import time
import uuid

import psutil

from .engine import LINE_FIELDS, inspect_engine, prepare_model
from .io import identity, read_json, sha256_file, write_csv, write_json
from .manifest import load_manifest
from .pipeline import code_provenance, recognize_page
from .quality import FLAG_FIELDS, column_geometry, line_diagnostics, review_body_y, verify_run
from .source import SourceUnavailable


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_plan(path, manifest):
    plan = read_json(path)
    if plan.get("format") != "bpl-batch-plan-v1" or plan.get("manifest_id") != manifest["manifest_id"]:
        raise ValueError("Batch plan format or source manifest does not match")
    leaves = plan["leaves"]
    if not 1 <= len(leaves) <= 100 or any(type(n) is not int for n in leaves) or len(set(leaves)) != len(leaves):
        raise ValueError("This stage requires 1–100 distinct scanned leaves")
    allowed = {p["leaf_num"] for p in manifest["pages"] if p["selected_for_ocr"]}
    if not set(leaves).issubset(allowed):
        raise ValueError("Batch plan includes out-of-scope leaves")
    policy = plan["policy"]
    for key in ("engine_timeout_s", "sample_interval_s", "retry_backoff_s"):
        if not 0 < policy[key] <= 600:
            raise ValueError("Invalid bounded batch policy: " + key)
    if type(policy["max_page_attempts"]) is not int or not 1 <= policy["max_page_attempts"] <= 3:
        raise ValueError("Use 1–3 attempts per page; interrupted attempts do not consume this budget")
    source = policy["source"]
    if (not 1 <= source["bookreader_attempts"] <= 3 or not 0 <= source["backoff_s"] <= 60 or
            not all(0 < source[k] <= 120 for k in ("iiif_timeout_s", "bookreader_timeout_s"))):
        raise ValueError("Invalid bounded source policy")
    if not source["bookreader_base"].startswith("https://") or not source["bookreader_zip"].endswith("/" + manifest["config"]["image_archive"]):
        raise ValueError("Fallback must identify the configured image archive")
    return plan


@contextmanager
def batch_lock(folder):
    """An OS advisory lock is released even if the Python worker is killed."""
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "worker.lock").open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Another worker holds this batch lock") from error
        try:
            handle.seek(0)
            handle.truncate()
            handle.write(f"{socket.gethostname()} pid={os.getpid()}\n")
            handle.flush()
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class CaptureQuarantined(ValueError):
    def __init__(self, record, rows, flags, diagnostic, reasons):
        self.review = record, rows, flags, diagnostic
        super().__init__("; ".join(reasons))


def checked_page(folder, manifest, execution):
    record, rows, _ = verify_run(folder, manifest)
    if record["code"]["code_sha256"] != execution["code_sha256"] or record["settings"]["engine_build"] != execution["engine_build"]:
        raise ValueError("Run code/engine differs from the pinned batch execution")
    page = record["page"]
    geometry = column_geometry(rows, page["expected_width"], review_body_y(page))
    flags, counts, segments = line_diagnostics(rows, page, geometry)
    columns = Counter(f["column_candidate"] for f in flags)
    reasons = []
    if geometry["status"] != "two_start_clusters":
        reasons.append("Unresolved two-column geometry")
    if not columns["L"] or not columns["R"]:
        reasons.append("A review column has no detected rows")
    body_rows = columns["L"] + columns["R"]
    cross_fraction = counts["cross_gutter_candidate"] / body_rows if body_rows else 0
    if counts["cross_gutter_candidate"] >= 3 and cross_fraction >= .1:
        reasons.append("Systematic cross-column merge candidates: >=3 rows and >=10% of review-body rows")
    diagnostic = {"column_geometry": geometry, "column_rows": dict(columns),
                  "native_body_column_segments": segments, "flag_counts": dict(counts),
                  "cross_gutter_fraction": cross_fraction, "quarantine_reasons": reasons,
                  "quality_status": "quarantined" if reasons else "review_required", "detected_lines": len(rows),
                  "recognized_words": sum(r["word_count"] for r in rows)}
    if reasons:
        raise CaptureQuarantined(record, rows, flags, diagnostic, reasons)
    return record, rows, flags, diagnostic


def finish_attempt(entry, attempt, folder, manifest, execution):
    try:
        record, _, _, diagnostic = checked_page(folder, manifest, execution)
    except (ValueError, KeyError, OSError) as error:
        attempt.update(status="quarantined", error=type(error).__name__ + ": " + str(error))
        entry.update(status="quarantined", reason=attempt["error"])
        if isinstance(error, CaptureQuarantined):
            entry["diagnostics"] = error.review[3]
    else:
        attempt.update(status="completed", run_id=record["run_id"])
        entry.update(status="completed", run_directory=attempt["run_directory"],
                     run_id=record["run_id"], diagnostics=diagnostic)
        entry.pop("reason", None)
    attempt.setdefault("finished_at_utc", utc_now())


def stop_abandoned_engine(record):
    child = record.get("engine_process")
    if not child:
        return
    if record["runtime"].get("hostname") != socket.gethostname():
        raise RuntimeError("An incomplete run belongs to another host; verify that its native worker has stopped before resuming")
    try:
        process = psutil.Process(child["pid"])
        if abs(process.create_time() - child["create_time"]) < .01:
            process.terminate()
            try:
                process.wait(timeout=3)
            except psutil.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
    except psutil.NoSuchProcess:
        pass


def recover(state, work, manifest):
    for session in state["sessions"]:
        if session["status"] == "running":
            session.update(status="abandoned", recovered_at_utc=utc_now(),
                           wall_s=None, note="Hard-stop duration is unknown and excluded from measured active wall time")
    for entry in state["pages"]:
        if entry["status"] == "completed":
            attempt = entry["attempts"][-1]
            finish_attempt(entry, attempt, work / entry["run_directory"], manifest, state["execution"])
        elif entry["status"] in ("running", "interrupted"):
            attempt = entry["attempts"][-1]
            folder = work / attempt["run_directory"] if attempt.get("run_directory") else None
            record = read_json(folder / "run.json") if folder and (folder / "run.json").exists() else None
            if record and record["status"] == "completed":
                finish_attempt(entry, attempt, folder, manifest, state["execution"])
                state["recovery_events"].append({"leaf_num": entry["leaf_num"], "event": "adopted_completed_run_before_checkpoint", "at_utc": utc_now()})
            else:
                if record:
                    stop_abandoned_engine(record)
                attempt.update(status="interrupted", error="Recovered incomplete attempt; original run retained")
                attempt.setdefault("finished_at_utc", utc_now())
                entry["status"] = "interrupted"
                state["recovery_events"].append({"leaf_num": entry["leaf_num"], "event": "recovered_incomplete_attempt", "at_utc": utc_now()})


def export_batch(state, work, manifest, folder):
    """Export only checked captures; all failed/quarantined leaves remain in coverage."""
    all_lines, quarantined_lines, all_flags, pages, attempts, receipts = [], [], [], [], [], []
    flags_total = Counter()
    for entry in state["pages"]:
        for number, attempt in enumerate(entry["attempts"], 1):
            record_path = work / attempt.get("run_directory", "__missing__") / "run.json"
            record = read_json(record_path) if record_path.exists() else {}
            attempts.append({"leaf_num": entry["leaf_num"], "attempt": number, "status": attempt["status"],
                             "run_directory": attempt.get("run_directory", ""), "error": attempt.get("error", ""),
                             "wall_s": record.get("durations_s", {}).get("wall", ""),
                             "engine_s": record.get("durations_s", {}).get("engine", ""),
                             "peak_process_tree_rss_bytes": record.get("resources", {}).get("peak_process_tree_rss_bytes", "")})
            if record:
                receipts.append({"leaf_num": entry["leaf_num"], "attempt": number, "batch_status": attempt["status"], "record": record})
        row = {"leaf_num": entry["leaf_num"], "status": entry["status"], "attempts": len(entry["attempts"]),
               "reason": entry.get("reason", ""), "printed_page": "", "ocr_role": "", "detected_lines": 0,
               "exported_lines": 0,
               "recognized_words": 0, "cache_reused": "", "retrieval_method": "", "engine_s": "", "wall_s": "",
               "peak_process_tree_rss_bytes": "", "sampled_cpu_seconds_lower_bound": "", "tree_enumeration_failures": "",
               "native_body_column_segments": "", "quality_status": "", "run_id": entry.get("run_id", "")}
        page = next(p for p in manifest["pages"] if p["leaf_num"] == entry["leaf_num"])
        row.update(printed_page=page["printed_page"], ocr_role=page["ocr_role"])
        review = None
        if entry["status"] == "completed":
            review = checked_page(work / entry["run_directory"], manifest, state["execution"])
        elif entry["status"] == "quarantined" and entry["attempts"][-1].get("run_directory"):
            try:
                checked_page(work / entry["attempts"][-1]["run_directory"], manifest, state["execution"])
            except CaptureQuarantined as error:
                review = error.review
            except (ValueError, KeyError, OSError):
                pass  # A corrupted capture has no certified line export.
        if review:
            record, lines, flags, diagnostic = review
            (all_lines if entry["status"] == "completed" else quarantined_lines).extend(lines)
            all_flags.extend(flags)
            flags_total.update(diagnostic["flag_counts"])
            source, resources = record["source"], record["resources"]
            row.update(detected_lines=len(lines), exported_lines=len(lines) if entry["status"] == "completed" else 0,
                       recognized_words=diagnostic["recognized_words"],
                       cache_reused=source["cache_reused"], retrieval_method=source.get("retrieval_method", "bookreader_native_alias" if source.get("retrieval_url") else "iiif_native_or_verified_cache"),
                       engine_s=record["durations_s"]["engine"], wall_s=record["durations_s"]["wall"],
                       peak_process_tree_rss_bytes=resources["peak_process_tree_rss_bytes"],
                       sampled_cpu_seconds_lower_bound=resources["sampled_cpu_seconds_lower_bound"],
                       tree_enumeration_failures=resources["tree_enumeration_failures"],
                       native_body_column_segments=diagnostic["native_body_column_segments"], quality_status=diagnostic["quality_status"],
                       run_id=record["run_id"])
        pages.append(row)
    write_csv(folder / "pages.csv", pages, list(pages[0]))
    write_csv(folder / "attempts.csv", attempts, ("leaf_num", "attempt", "status", "run_directory", "error", "wall_s", "engine_s", "peak_process_tree_rss_bytes"))
    write_csv(folder / "lines.csv", all_lines, LINE_FIELDS)
    write_csv(folder / "quarantined_lines.csv", quarantined_lines, LINE_FIELDS)
    write_csv(folder / "line_flags.csv", all_flags, FLAG_FIELDS)
    write_json(folder / "run_records.json", receipts)
    summary = {"format": "bpl-batch-summary-v1", "batch_id": state["batch_id"], "plan_id": state["plan_id"],
               "manifest_id": manifest["manifest_id"], "status": state["status"], "planned_pages": len(pages),
               "page_statuses": dict(Counter(p["status"] for p in pages)), "attempt_statuses": dict(Counter(a["status"] for a in attempts)),
               "detected_lines": len(all_lines), "exported_lines": len(all_lines),
               "captured_native_lines": sum(p["detected_lines"] for p in pages), "quarantined_lines": len(quarantined_lines),
               "recognized_words": sum(p["recognized_words"] for p in pages),
               "accepted_recognized_words": sum(p["recognized_words"] for p in pages if p["status"] == "completed"),
               "capture_attempt_statuses": dict(Counter(r["record"]["status"] for r in receipts)),
               "flag_counts": dict(flags_total), "source_methods": dict(Counter(p["retrieval_method"] for p in pages if p["retrieval_method"])),
               "source_cache_reused_pages": sum(p["cache_reused"] is True for p in pages),
               "measured_session_wall_s": sum(s.get("wall_s") or 0 for s in state["sessions"]),
               "unknown_duration_sessions": sum(s.get("wall_s") is None for s in state["sessions"]),
               "successful_engine_s": sum(p["engine_s"] for p in pages if p["status"] == "completed"),
               "captured_native_engine_s": sum(r["record"].get("durations_s", {}).get("engine", 0) for r in receipts if r["record"]["status"] == "completed"),
               "all_recorded_attempt_wall_s": sum(a["wall_s"] for a in attempts if isinstance(a["wall_s"], (int, float))),
               "peak_process_tree_rss_bytes": max((a["peak_process_tree_rss_bytes"] for a in attempts if isinstance(a["peak_process_tree_rss_bytes"], int)), default=0),
               "tree_enumeration_failures": sum(r["record"].get("resources", {}).get("tree_enumeration_failures", 0) for r in receipts),
               "scope_notes": state["plan"].get("scope_notes", []),
               "meaning": "Checked raw captures and diagnostic candidates, not validated entries, error rates or people. All attempts, including interrupted/failed ones, are retained. Sampled RSS is a process sum and CPU is a sampled lower bound; measured sessions exclude downtime and unknown hard-stop durations."}
    write_json(folder / "summary.json", summary)
    return summary


def review_batch(manifest_path, work_dir, batch_dir, output_dir):
    """Re-evaluate saved captures with current QA, leaving native runs/checkpoints intact."""
    folder, output = Path(batch_dir).resolve(), Path(output_dir).resolve()
    if folder == output:
        raise ValueError("Offline review output must differ from the original batch directory")
    manifest, work = load_manifest(manifest_path), Path(work_dir).resolve()
    with batch_lock(folder):
        checkpoint = folder / "checkpoint.json"
        state = deepcopy(read_json(checkpoint))
        if state["status"] == "running" or state["plan"]["manifest_id"] != manifest["manifest_id"]:
            raise ValueError("Review requires a stopped batch and its original manifest")
        metadata = {"format": "bpl-offline-batch-review-v1", "reviewed_at_utc": utc_now(),
                    "input_checkpoint_sha256": sha256_file(checkpoint), "capture_status": state["status"],
                    "capture_execution": state["execution"], "review_code": code_provenance(),
                    "quarantine_policy": "Unresolved columns, integrity failures, or >=3 cross-gutter candidates comprising >=10% of diagnostic body rows",
                    "native_outputs_modified": False, "ocr_invocations": 0}
        for entry in state["pages"]:
            if entry["status"] == "completed":
                finish_attempt(entry, entry["attempts"][-1], work / entry["run_directory"], manifest, state["execution"])
        state["status"] = "completed" if all(p["status"] == "completed" for p in state["pages"]) else "needs_attention"
        output.mkdir(parents=True, exist_ok=True)
        summary = export_batch(state, work, manifest, output)
        metadata.update(page_statuses=summary["page_statuses"], captured_native_lines=summary["captured_native_lines"],
                        accepted_lines=summary["exported_lines"], quarantined_lines=summary["quarantined_lines"])
        write_json(output / "review.json", metadata)
        write_json(output / "review_checkpoint.json", state)
        return summary


def run_batch(manifest_path, plan_path, work_dir, batch_dir, *, executable=None, max_pages=None):
    if max_pages is not None and max_pages < 1:
        raise ValueError("max-pages must be positive")
    manifest = load_manifest(manifest_path)
    plan = load_plan(plan_path, manifest)
    work, folder = Path(work_dir).resolve(), Path(batch_dir).resolve()
    info = inspect_engine(manifest["config"], executable)
    execution = {"code_sha256": code_provenance()["code_sha256"], "engine_build": info["version_text"],
                 "machine": platform.machine(), "python": platform.python_version(), "platform": platform.system(),
                 "psutil": psutil.__version__, "omp_thread_limit": os.environ.get("OMP_THREAD_LIMIT")}
    with batch_lock(folder):
        state_path = folder / "checkpoint.json"
        if state_path.exists():
            state = read_json(state_path)
            if state["plan_id"] != identity(plan) or state["execution"] != execution or state["work_directory"] != str(work):
                raise ValueError("Plan, code, engine, runtime controls or work directory changed; create a new batch directory")
            recover(state, work, manifest)
        else:
            if any(p.name != "worker.lock" for p in folder.iterdir()):
                raise ValueError("New batch directory must be empty")
            state = {"format": "bpl-batch-checkpoint-v1", "batch_id": uuid.uuid4().hex, "plan_id": identity(plan),
                     "plan": plan, "execution": execution, "work_directory": str(work), "created_at_utc": utc_now(),
                     "status": "pending", "pages": [{"leaf_num": leaf, "status": "pending", "attempts": []} for leaf in plan["leaves"]],
                     "sessions": [], "recovery_events": []}
        def save():
            write_json(state_path, state)
        save()
        # Model validation is outside page retries: configuration corruption must stop the batch.
        prepare_model(manifest["config"], work)
        session = {"session_id": uuid.uuid4().hex, "started_at_utc": utc_now(), "status": "running",
                   "initial_completed_pages": sum(p["status"] == "completed" for p in state["pages"]), "new_page_attempts": 0,
                   "hostname": socket.gethostname(), "pid": os.getpid()}
        state["sessions"].append(session)
        state["status"] = "running"
        save()
        start = time.perf_counter()
        previous_term = signal.getsignal(signal.SIGTERM)
        def terminate(signum, frame):
            raise KeyboardInterrupt("Termination signal " + str(signum))
        signal.signal(signal.SIGTERM, terminate)
        policy, scheduled = plan["policy"], 0
        try:
            for entry in state["pages"]:
                if entry["status"] in ("completed", "quarantined", "failed"):
                    continue
                if max_pages is not None and scheduled >= max_pages:
                    break
                scheduled += 1
                while sum(a["status"] == "failed" for a in entry["attempts"]) < policy["max_page_attempts"]:
                    attempt = {"attempt_id": uuid.uuid4().hex, "session_id": session["session_id"],
                               "status": "running", "started_at_utc": utc_now()}
                    entry["attempts"].append(attempt)
                    entry["status"] = "running"
                    session["new_page_attempts"] += 1
                    save()
                    print(f"leaf {entry['leaf_num']}: starting attempt {len(entry['attempts'])}", flush=True)
                    def created(path, record):
                        attempt["run_directory"] = path.relative_to(work).as_posix()
                        save()
                    try:
                        path, record = recognize_page(manifest_path, entry["leaf_num"], work, executable=executable,
                                                      timeout=policy["engine_timeout_s"], source_policy=policy["source"],
                                                      sample_interval=policy["sample_interval_s"], on_created=created,
                                                      context={"batch_id": state["batch_id"], "attempt_id": attempt["attempt_id"]})
                        finish_attempt(entry, attempt, path, manifest, execution)
                        save()
                        print(f"leaf {entry['leaf_num']}: {entry['status']}", flush=True)
                        break
                    except KeyboardInterrupt as error:
                        attempt.update(status="interrupted", error=str(error), finished_at_utc=utc_now())
                        entry["status"] = "interrupted"
                        save()
                        raise
                    except Exception as error:
                        retryable = isinstance(error, (SourceUnavailable, subprocess.TimeoutExpired))
                        status = "quarantined" if isinstance(error, ValueError) else "failed"
                        attempt.update(status=status, error=type(error).__name__ + ": " + str(error), finished_at_utc=utc_now())
                        failures = sum(a["status"] == "failed" for a in entry["attempts"])
                        entry.update(status="pending" if retryable and failures < policy["max_page_attempts"] else status,
                                     reason=attempt["error"])
                        save()
                        print(f"leaf {entry['leaf_num']}: {attempt['error']}", flush=True)
                        if entry["status"] != "pending":
                            break
                        time.sleep(policy["retry_backoff_s"])
            counts = Counter(p["status"] for p in state["pages"])
            state["status"] = "completed" if counts["completed"] == len(state["pages"]) else ("paused" if counts["pending"] or counts["interrupted"] else "needs_attention")
            session["status"] = state["status"]
        except KeyboardInterrupt:
            state["status"] = session["status"] = "interrupted"
            raise
        except BaseException:
            state["status"] = session["status"] = "failed"
            raise
        finally:
            signal.signal(signal.SIGTERM, previous_term)
            session.update(wall_s=time.perf_counter() - start, finished_at_utc=utc_now())
            save()
            export_batch(state, work, manifest, folder)
        return read_json(folder / "summary.json")
