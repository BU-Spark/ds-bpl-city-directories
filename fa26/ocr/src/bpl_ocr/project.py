"""Disjoint volume assignments and sequential small batches for independent machines."""

from collections import Counter
from copy import deepcopy
from pathlib import Path
import re

from .batch import batch_lock, load_plan, run_batch, utc_now
from .io import identity, read_json, write_csv, write_json
from .manifest import load_manifest
from .pipeline import code_provenance


def partition(assignments, output, *, batch_size=100, repo_root=None):
    if type(batch_size) is not int or not 1 <= batch_size <= 100:
        raise ValueError("Use 1–100 selected physical pages per batch")
    root, output = Path(repo_root or Path.cwd()).resolve(), Path(output).resolve()
    specifications, inventory, seen = [], [], set()
    plans = {}
    for owner, manifest_path in assignments:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", owner):
            raise ValueError("Use an ASCII owner name containing letters, digits, - or _")
        path = (root / manifest_path).resolve()
        reference = path.relative_to(root).as_posix()
        manifest = load_manifest(path)
        config = manifest["config"]
        alias = path.parent.name
        assignment_id = owner.lower() + "-" + alias
        if any(a["assignment_id"] == assignment_id or a["volume_id"] == config["volume_id"] for a in specifications):
            raise ValueError("Each volume must be assigned exactly once")
        pages = [p for p in manifest["pages"] if p["selected_for_ocr"]]
        if not pages:
            raise ValueError("An assigned volume has no selected pages")
        metadata = read_json(path.parent / "source/metadata.json")
        policy = {"max_page_attempts": 2, "engine_timeout_s": 120, "sample_interval_s": .1,
                  "retry_backoff_s": 2,
                  "source": {"iiif_timeout_s": 15, "bookreader_timeout_s": 30, "bookreader_attempts": 2,
                             "backoff_s": 1, "bookreader_base": "https://" + metadata["d1"] + "/BookReader/BookReaderImages.php",
                             "bookreader_zip": metadata["dir"] + "/" + config["image_archive"]}}
        batches = []
        for start in range(0, len(pages), batch_size):
            selected = pages[start:start + batch_size]
            batch_id = f"{alias}-{len(batches)+1:03d}"
            plan_file = f"{alias}/{batch_id}.json"
            plan = {"format": "bpl-batch-plan-v1", "manifest_id": manifest["manifest_id"],
                    "selection_method": "Disjoint selected physical pages in manifest scan order; no alphabetical guessing or overlap.",
                    "leaves": [p["leaf_num"] for p in selected], "policy": deepcopy(policy),
                    "assignment_id": assignment_id, "batch_id": batch_id,
                    "scope_notes": [config["scope"]["review_notes"],
                                    "Capture only; preserve native text and all quarantined/failed attempts. Reconstruct cross-page entries after collection."]}
            plans[plan_file] = plan
            batches.append({"batch_id": batch_id, "plan_file": plan_file, "plan_id": identity(plan), "pages": len(selected)})
            for page in selected:
                key = config["volume_id"], page["leaf_num"]
                if key in seen:
                    raise ValueError("Overlapping volume/leaf assignment")
                seen.add(key)
                inventory.append({"owner": owner, "assignment_id": assignment_id, "volume_id": config["volume_id"],
                                  "page_id": page["page_id"], "leaf_num": page["leaf_num"], "printed_page": page["printed_page"],
                                  "ocr_role": page["ocr_role"], "manifest_id": manifest["manifest_id"], "batch_id": batch_id,
                                  "plan_file": plan_file})
        specifications.append({"assignment_id": assignment_id, "owner": owner, "volume_id": config["volume_id"],
                               "manifest": reference, "manifest_id": manifest["manifest_id"], "pages": len(pages),
                               "model": config["ocr"], "batches": batches})
    if not specifications:
        raise ValueError("Provide at least one owner=manifest assignment")
    payload = {"format": "bpl-project-plan-v1", "batch_size": batch_size, "total_pages": len(inventory),
               "assignments": specifications}
    project = {**payload, "project_id": identity(payload)}
    # Reject accidental edits/reassignment of a published plan directory.
    if output.exists() and any(output.iterdir()):
        if not (output / "project.json").exists() or read_json(output / "project.json") != project:
            raise ValueError("Output plan directory is already in use; choose a new directory")
    for name, plan in plans.items():
        write_json(output / name, plan)
    write_csv(output / "pages.csv", inventory, list(inventory[0]))
    write_json(output / "project.json", project)
    return project


def project_selected_leaves(manifest):
    return [p["leaf_num"] for p in manifest["pages"] if p["selected_for_ocr"]]


def load_assignment(project_path, assignment_id, repo_root=None):
    project_path = Path(project_path).resolve()
    project = read_json(project_path)
    payload = {k: v for k, v in project.items() if k != "project_id"}
    if project.get("format") != "bpl-project-plan-v1" or identity(payload) != project.get("project_id"):
        raise ValueError("Project plan changed without a valid identity")
    choices = [a for a in project["assignments"] if a["assignment_id"] == assignment_id]
    if len(choices) != 1:
        available = ", ".join(a["assignment_id"] for a in project["assignments"]) or "(none)"
        raise ValueError(f"Unknown assignment ID {assignment_id!r}. Available: {available}")
    assignment = choices[0]
    root = Path(repo_root or Path.cwd()).resolve()
    manifest_path = root / assignment["manifest"]
    manifest = load_manifest(manifest_path)
    if manifest["manifest_id"] != assignment["manifest_id"] or manifest["config"]["ocr"] != assignment["model"]:
        raise ValueError("Assignment manifest/model changed")
    all_leaves, batches = [], []
    for batch in assignment["batches"]:
        path = (project_path.parent / batch["plan_file"]).resolve()
        path.relative_to(project_path.parent)
        plan = load_plan(path, manifest)
        if identity(plan) != batch["plan_id"] or len(plan["leaves"]) != batch["pages"]:
            raise ValueError("Batch plan changed")
        if plan.get("assignment_id") != assignment_id:
            raise ValueError("Batch plan assignment_id does not match selected worker")
        all_leaves.extend(plan["leaves"])
        batches.append((batch, path, plan))
    selected = project_selected_leaves(manifest)
    selected_set = set(selected)
    if len(set(all_leaves)) != len(all_leaves) or len(all_leaves) != assignment["pages"]:
        raise ValueError("Assignment coverage is duplicated or page count mismatch")
    if not set(all_leaves).issubset(selected_set):
        raise ValueError("Assignment includes pages outside the selected OCR scope")
    expected_subset = [leaf for leaf in selected if leaf in set(all_leaves)]
    if all_leaves != expected_subset:
        raise ValueError("Assignment coverage is out of selected-page order")
    verify_project_coverage(project_path, repo_root=root)
    return project, assignment, manifest_path, batches


def verify_project_coverage(project_path, *, repo_root=None):
    """Ensure the union of all assignments covers every selected page exactly once."""
    project_path = Path(project_path).resolve()
    project = read_json(project_path)
    root = Path(repo_root or Path.cwd()).resolve()
    if not project.get("assignments"):
        raise ValueError("Project has no assignments")
    owned = {}
    selected = None
    for assignment in project["assignments"]:
        manifest = load_manifest(root / assignment["manifest"])
        current = project_selected_leaves(manifest)
        if selected is None:
            selected = current
        elif current != selected:
            raise ValueError("Assignments disagree about selected page coverage")
        leaves = []
        for batch in assignment["batches"]:
            plan = load_plan((project_path.parent / batch["plan_file"]).resolve(), manifest)
            if plan.get("assignment_id") != assignment["assignment_id"]:
                raise ValueError("Batch plan assignment_id does not match project assignment")
            leaves.extend(plan["leaves"])
        if len(set(leaves)) != len(leaves) or len(leaves) != assignment["pages"]:
            raise ValueError(f"Assignment {assignment['assignment_id']} has duplicate or mismatched pages")
        for leaf in leaves:
            if leaf in owned:
                raise ValueError(
                    f"Leaf {leaf} is assigned to both {owned[leaf]} and {assignment['assignment_id']}")
            owned[leaf] = assignment["assignment_id"]
    if set(owned) != set(selected) or len(owned) != project["total_pages"]:
        raise ValueError("Project assignments do not cover the selected OCR pages exactly once")
    return True


def assignment_status(project_path, assignment_id, data_dir, *, repo_root=None):
    project, assignment, _, batches = load_assignment(project_path, assignment_id, repo_root)
    folder = Path(data_dir).resolve() / assignment_id
    coverage = []
    for batch, _, plan in batches:
        checkpoint = folder / "batches" / batch["batch_id"] / "checkpoint.json"
        states = {}
        if checkpoint.exists():
            state = read_json(checkpoint)
            if state["plan_id"] != batch["plan_id"] or [p["leaf_num"] for p in state["pages"]] != plan["leaves"]:
                raise ValueError("Checkpoint belongs to a different batch plan")
            states = {p["leaf_num"]: p for p in state["pages"]}
        for leaf in plan["leaves"]:
            entry = states.get(leaf, {})
            coverage.append({"volume_id": assignment["volume_id"], "leaf_num": leaf,
                             "batch_id": batch["batch_id"], "status": entry.get("status", "not_started"),
                             "attempts": len(entry.get("attempts", [])), "reason": entry.get("reason", ""),
                             "run_directory": entry.get("run_directory", "")})
    counts = Counter(p["status"] for p in coverage)
    unfinished = any(p["status"] in ("not_started", "pending", "running", "interrupted") for p in coverage)
    status = "incomplete" if unfinished else ("needs_attention" if counts["quarantined"] or counts["failed"] else "completed")
    return {"format": "bpl-assignment-status-v1", "project_id": project["project_id"],
            "assignment_id": assignment_id, "owner": assignment["owner"], "pages": len(coverage),
            "status": status, "page_statuses": dict(counts), "coverage": coverage,
            "meaning": "Status reported by local checkpoints, not a byte revalidation or proof that remote work has not run."}


def run_assignment(project_path, assignment_id, data_dir, *, repo_root=None, executable=None, max_batches=None):
    if max_batches is not None and max_batches < 1:
        raise ValueError("max-batches must be positive")
    project, assignment, manifest, batches = load_assignment(project_path, assignment_id, repo_root)
    folder = Path(data_dir).resolve() / assignment_id
    with batch_lock(folder):
        execution = code_provenance()["code_sha256"]
        receipt_path = folder / "assignment.json"
        if receipt_path.exists():
            receipt = read_json(receipt_path)
            if (receipt["project_id"], receipt["assignment_id"], receipt["code_sha256"]) != (project["project_id"], assignment_id, execution):
                raise ValueError("Assignment plan/code changed; use a new data directory")
        else:
            write_json(receipt_path, {"project_id": project["project_id"], "assignment_id": assignment_id,
                                      "code_sha256": execution, "created_at_utc": utc_now()})
        count = 0
        try:
            for batch, path, plan in batches:
                checkpoint = folder / "batches" / batch["batch_id"] / "checkpoint.json"
                if checkpoint.exists():
                    saved = read_json(checkpoint)
                    if saved["plan_id"] == batch["plan_id"] and saved["status"] in ("completed", "needs_attention"):
                        # Revalidation still runs; this does not consume the additional-batch limit.
                        additional = False
                    else:
                        additional = True
                else:
                    additional = True
                if additional and max_batches is not None and count >= max_batches:
                    break
                if code_provenance()["code_sha256"] != execution:
                    raise ValueError("Package code changed while this assignment was running")
                print(f"{assignment_id}: {batch['batch_id']} ({batch['pages']} pages)", flush=True)
                run_batch(manifest, path, folder / "work", folder / "batches" / batch["batch_id"], executable=executable)
                count += additional
                report = assignment_status(project_path, assignment_id, data_dir, repo_root=repo_root)
                write_json(folder / "status.json", {k: v for k, v in report.items() if k != "coverage"})
                write_csv(folder / "coverage.csv", report["coverage"], list(report["coverage"][0]))
        finally:
            report = assignment_status(project_path, assignment_id, data_dir, repo_root=repo_root)
            write_json(folder / "status.json", {k: v for k, v in report.items() if k != "coverage"})
            write_csv(folder / "coverage.csv", report["coverage"], list(report["coverage"][0]))
        return {k: v for k, v in report.items() if k != "coverage"}
