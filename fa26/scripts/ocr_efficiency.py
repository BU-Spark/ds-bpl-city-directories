"""Additive resource measurement for the existing BPL line OCR pipeline.

Original source/, results/, adapters and recognition notebook are read-only.
Fresh inference and resource telemetry are stored only under efficiency/.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import csv
import json
from pathlib import Path
import platform
import shutil
import tempfile
import time
import uuid
import zipfile

import ocr_pipeline as ocr

METRICS_VERSION = "bpl-ocr-efficiency-v1"
SUMMARY_FIELDS = ["model", "run_status", "measured_lines", "device", "hardware", "precision", "setup_s", "load_s",
                  "processing_s", "mean_s_per_line", "mean_s_per_page", "pages_per_hour",
                  "peak_ram_mib", "peak_vram_allocated_mib", "gpu_device_peak_mib",
                  "mean_cpu_pct", "mean_gpu_pct", "export_s", "wall_s"]


def import_efficiency_bundle(archive, root):
    """Extract the old or measured bundle without regenerating any old results."""
    root = Path(root)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError("Use the already loaded ROOT or a fresh Colab runtime.")
    with tempfile.TemporaryDirectory() as temporary:
        staging = Path(temporary) / "data"
        with zipfile.ZipFile(archive) as bundle:
            members = [i for i in bundle.infolist() if not i.is_dir() and not any(
                p.startswith(".") or p == "__MACOSX" for p in Path(i.filename).parts)]
            indexes = [i.filename for i in members if i.filename.endswith("source/index.json")]
            if len(indexes) != 1 or sum(i.file_size for i in members) > 500_000_000:
                raise ValueError("Upload one common source/results ZIP, optionally with efficiency/.")
            prefix = indexes[0][:-len("source/index.json")]
            for item in members:
                if not item.filename.startswith(prefix):
                    continue
                relative = Path(item.filename[len(prefix):])
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("Unsafe ZIP path")
                if (not relative.parts or relative.parts[0] not in ("source", "results", "efficiency")
                        or relative.suffix not in (".jpg", ".json", ".jsonl", ".csv", ".tsv", ".txt")):
                    continue
                if item.file_size > 100_000_000:
                    raise ValueError("ZIP member too large")
                destination = staging / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(bundle.read(item))
        index = ocr.load_sources(staging)
        shutil.copytree(staging, root, dirs_exist_ok=True)
    return index


def pack_efficiency(root, destination):
    root, destination = Path(root), Path(destination)
    if root.resolve() in destination.resolve().parents:
        raise ValueError("Save transfer ZIP outside the data folder")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name in ("source", "results", "efficiency"):
            for path in sorted((root / name).rglob("*")):
                if path.is_file() and not any(p.startswith(".") for p in path.relative_to(root).parts):
                    bundle.write(path, path.relative_to(root))
    partial.replace(destination)
    return destination


def measurement_protocol(index, line_limit=None, warmup_lines=1):
    all_lines = ocr.visible_lines(index)
    if line_limit is not None and (type(line_limit) is not int or line_limit < 1):
        raise ValueError("line_limit must be None or a positive integer")
    if type(warmup_lines) is not int or warmup_lines < 0:
        raise ValueError("warmup_lines must be a nonnegative integer")
    count = min(line_limit or len(all_lines), len(all_lines))
    positions = [round(i*(len(all_lines)-1)/(count-1)) for i in range(count)] if count > 1 else [0]
    selected = [all_lines[i] for i in positions]
    protocol = {"version": METRICS_VERSION, "source_id": index["source_id"],
                "line_ids": [r["line_id"] for r in selected], "full_scope": count == len(all_lines),
                "lines_per_page": dict(Counter(str(r["printed_page"]) for r in selected)),
                "warmup_lines": min(warmup_lines, count), "batch_size": 1,
                "pipeline_sha256": ocr.sha_file(ocr.__file__), "measurement_sha256": ocr.sha_file(__file__),
                "scope": index["scope"],
                "policy": "Fresh line recognition; no prediction cache; original RGB crops; same ordered inputs for every engine."}
    protocol["protocol_id"] = ocr.identity(protocol)
    return protocol, selected


def _save_csv(path, rows, fields):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _mib(value):
    return value / 1024**2 if value is not None else None


def _reset_before_load(engine, device):
    """Prevent a previous trial's allocator high-water mark leaking into a new run."""
    if not str(device).startswith(("cuda", "gpu")):
        return "not_used_cpu"
    import sys
    framework = sys.modules.get("paddle" if engine == "paddleocr" else "torch")
    if framework is None:
        return "framework_not_loaded; allocator starts with framework initialization"
    try:
        cuda = framework.device.cuda if engine == "paddleocr" else framework.cuda
        cuda.synchronize()
        names = ("reset_max_memory_allocated", "reset_max_memory_reserved") if engine == "paddleocr" else ("reset_peak_memory_stats",)
        for name in names:
            method = getattr(cuda, name, None)
            if method:
                method()
        return "reset_before_load"
    except Exception as error:
        return "reset_unavailable: " + type(error).__name__


def _pins(root, engine):
    path = Path(root) / "results/models.json"
    models = json.loads(path.read_text()) if path.exists() else {}
    model = models.get(engine, {})
    return model.get("settings_history", {}).get(model.get("active_settings_id"), {})


def write_summary(root, protocol_id):
    """Always retain five rows; never mix samples or present partial runs as full."""
    root = Path(root)
    candidates = {engine: [] for engine in ocr.ENGINES}
    for path in (root / "efficiency/runs").glob("*/*/metrics.json"):
        try:
            metric = json.loads(path.read_text())
            engine = metric.get("engine")
            if engine in candidates and metric.get("protocol_id") == protocol_id:
                candidates[engine].append(metric)
        except (ValueError, OSError):
            continue
    rows, selected_runs = [], {}
    for engine in ocr.ENGINES:
        matching = candidates[engine]
        eligible = [m for m in matching if m.get("comparison_eligible")]
        if not matching:
            rows.append({"model": engine, "run_status": "not_measured"})
            continue
        metric = max(eligible or matching, key=lambda m: m["run_id"])
        resource = metric.get("resources", {})
        framework = metric.get("framework_memory", {})
        metadata = metric.get("metadata", {})
        actual_device = metric.get("actual_device", "")
        hardware = metadata.get("gpu_name") or resource.get("gpu_name") if actual_device.startswith(("cuda", "gpu")) else resource.get("cpu_model")
        selected_runs[engine] = engine + "/" + metric["run_id"]
        rows.append({"model": engine, "run_status": metric["run_status"],
                     "measured_lines": metric["measured_lines"], "device": actual_device,
                     "hardware": hardware, "precision": metric.get("settings", {}).get("precision"),
                     "setup_s": metric.get("setup_seconds"), "load_s": metric.get("model_load_and_download_seconds"),
                     "processing_s": metric.get("processing_seconds"),
                     "mean_s_per_line": metric.get("mean_seconds_per_line"),
                     "mean_s_per_page": metric.get("mean_seconds_per_page_scope"),
                     "pages_per_hour": metric.get("page_scopes_per_hour"),
                     "peak_ram_mib": _mib(resource.get("peak_process_tree_rss_bytes_sampled")),
                     "peak_vram_allocated_mib": framework.get("gpu_peak_allocated_mib"),
                     "gpu_device_peak_mib": _mib(resource.get("gpu_peak_used_bytes_sampled")),
                     "mean_cpu_pct": resource.get("cpu_utilization_percent_one_core"),
                     "mean_gpu_pct": resource.get("gpu_utilization_percent_mean_sampled"),
                     "export_s": metric.get("export_seconds"), "wall_s": metric.get("run_wall_seconds")})
    _save_csv(root / "efficiency/summary.csv", rows, SUMMARY_FIELDS)
    ocr.write_json(root / "efficiency/summary_scope.json", {
        "protocol_id": protocol_id, "selected_runs": selected_runs,
        "selection": "Latest eligible complete run per model, otherwise latest incomplete run. Never combine different samples.",
        "units": "Seconds; MiB=2^20 bytes; CPU percent: one logical core=100%; GPU utilization/device memory: sampled whole device, not model attribution.",
        "scope": "Batch1 shared-line recognition. Original page161 scope is body only. No page throughput for smoke/incomplete runs.",
        "missing_values": "Blank = not measured/unavailable, never zero. GPU memory allocator peaks differ from whole-device sampled memory.",
        "averages": "CPU/GPU utilization averages cover the whole monitored run (load, warmup, processing, export/cleanup); per-line/page time covers processing only. load_s includes any weight download inside the adapter.",
        "timing": "wall_s covers load, warmup, processing, local OCR export and cleanup; excludes dependency setup, bundle import, final telemetry serialization and ZIP/browser transfer."})
    return root / "efficiency/summary.csv"


def run_efficiency(root, engine, *, device="auto", line_limit=None, warmup_lines=1,
                   setup_seconds=None, import_seconds=None, adapter_factory=None, monitor_factory=None):
    """Measure an independent fresh run. Existing recognized text is never reused."""
    root = Path(root)
    if engine not in ocr.ENGINES:
        raise ValueError("Unknown engine")
    # The notebook resolves this during measured setup. Direct callers resolve it
    # as environment preparation, before the model-run clock starts.
    if device == "auto" and adapter_factory is None:
        if engine == "tesseract":
            device = "cpu"
        elif engine == "paddleocr":
            import paddle
            device = "gpu:0" if paddle.is_compiled_with_cuda() and paddle.device.cuda.device_count() else "cpu"
        else:
            import torch
            device = "cuda:0" if torch.cuda.is_available() else "cpu"
    index = ocr.load_sources(root)
    protocol, selected = measurement_protocol(index, line_limit, warmup_lines)
    protocol_id = protocol["protocol_id"]
    ocr.write_json(root / "efficiency/protocols" / (protocol_id + ".json"), protocol)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid.uuid4().hex[:8]
    directory = root / "efficiency/runs" / engine / run_id
    directory.mkdir(parents=True)
    metric = {"version": METRICS_VERSION, "engine": engine, "run_id": run_id,
              "protocol_id": protocol_id, "source_id": index["source_id"], "requested_lines": len(selected),
              "measured_lines": 0, "full_scope": protocol["full_scope"], "setup_seconds": setup_seconds,
              "import_seconds": import_seconds, "run_status": "initializing", "comparison_eligible": False,
              "batch_size": 1, "warmup_lines": protocol["warmup_lines"], "device_requested": device,
              "python": platform.python_version(), "platform": platform.platform(),
              "cache_policy": "Prediction cache ignored. Weights may be cached; combined load/download is measured as observed, not guaranteed cold download.",
              "timing_scope": "processing includes source image reads, crop, recognizer preprocessing/inference/decode, GPU synchronization, raw logging and progress. No original OCR output is rewritten."}
    ocr.write_json(directory / "metrics.json", metric)
    adapter, image, records, page_records, monitor = None, None, [], [], None
    memory_phases, active_page_info = [], None
    clock = time.perf_counter()
    try:
        monitor = (monitor_factory or ResourceMonitor)(device, engine)
        monitor.start()
        started = time.perf_counter()
        metric["allocator_reset_before_load"] = _reset_before_load(engine, device)
        metric["model_cache_directory_existed"] = (root.parent / "bpl_efficiency_model_cache").exists()
        adapter = (adapter_factory or ocr.build_recognizer)(engine, device=device,
                  pinned_settings=_pins(root, engine), model_cache=root.parent / "bpl_efficiency_model_cache")
        synchronize(adapter)
        metric["model_load_and_download_seconds"] = time.perf_counter()-started
        metric["settings"] = adapter.settings
        metric["metadata"] = adapter.metadata
        metric["actual_device"] = getattr(adapter, "device", adapter.metadata.get("actual_device", device))
        import os
        metric["thread_environment"] = {k: os.environ.get(k) for k in ("OMP_NUM_THREADS", "OMP_THREAD_LIMIT", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")}
        framework = getattr(adapter, "framework", None)
        if framework is not None and hasattr(framework, "get_num_threads"):
            metric["framework_cpu_threads"] = framework.get_num_threads()
        memory_phases = [gpu_allocated(adapter)]
        pages = {p["printed_page"]: p for p in index["pages"]}
        started = time.perf_counter()
        for row in selected[:protocol["warmup_lines"]]:
            from PIL import Image
            with Image.open(root / pages[row["printed_page"]]["image"]) as original:
                with original.convert("RGB").crop(tuple(row["bbox"])) as tile:
                    adapter.predict(tile)
                    synchronize(adapter)
        metric["warmup_seconds"] = time.perf_counter()-started
        memory_phases.append(gpu_allocated(adapter))
        gpu_allocated(adapter, reset=True)
        started = time.perf_counter()
        metric["run_status"] = "processing"
        try:
            with (directory / "raw.jsonl").open("w", encoding="utf-8") as log:
                for number in sorted({r["printed_page"] for r in selected}):
                    page_clock = time.perf_counter()
                    page_lines = [r for r in selected if r["printed_page"] == number]
                    count_before = len(records)
                    active_page_info = {"printed_page": number, "selected_lines": len(page_lines)}
                    page = pages[number]
                    if ocr.sha_file(root / page["image"]) != page["sha256"]:
                        raise ValueError("Source bytes changed during measurement")
                    from PIL import Image
                    with Image.open(root / page["image"]) as original:
                        image = original.convert("RGB")
                    for row in page_lines:
                        synchronize(adapter)
                        request_clock = time.perf_counter()
                        record = {"line_id": row["line_id"], "printed_page": number, "bbox": row["bbox"],
                                  "input_id": ocr.line_identity(index, row)}
                        try:
                            with image.crop(tuple(row["bbox"])) as tile:
                                response = adapter.predict(tile)
                            synchronize(adapter)
                            if not isinstance(response.get("raw_text"), str) or response.get("status") not in ("completed", "empty", "truncated"):
                                raise ValueError("Invalid recognizer response")
                            record.update(response)
                        except Exception as error:
                            oom = "out of memory" in str(error).lower() or "outofmemory" in type(error).__name__.lower()
                            record.update(raw_text="", status="out_of_memory" if oom else "failed",
                                          error=type(error).__name__ + ": " + str(error))
                        record["request_seconds"] = time.perf_counter()-request_clock
                        record["raw_text_sha256"] = ocr.sha_text(record["raw_text"])
                        log.write(json.dumps(record, ensure_ascii=False) + "\n")
                        log.flush()
                        records.append(record)
                        if len(records) % 20 == 0 or len(records) == len(selected):
                            print(engine, len(records), "/", len(selected), record["status"], flush=True)
                        if record["status"] == "out_of_memory":
                            break
                    image.close()
                    image = None
                    page_records.append({**active_page_info, "measured_lines": len(records)-count_before,
                                         "processing_seconds": time.perf_counter()-page_clock,
                                         "page_status": "complete" if len(records)-count_before == len(page_lines) else "incomplete"})
                    active_page_info = None
                    if records and records[-1]["status"] == "out_of_memory":
                        break
        finally:
            if active_page_info is not None:
                page_records.append({**active_page_info, "measured_lines": len(records)-count_before,
                                     "processing_seconds": time.perf_counter()-page_clock, "page_status": "incomplete"})
            metric["processing_seconds"] = time.perf_counter()-started
        memory_phases.append(gpu_allocated(adapter))
        all_attempted = len(records) == len(selected)
        errors = any(r["status"] in ("failed", "out_of_memory") for r in records)
        metric["comparison_eligible"] = all_attempted and not errors
        metric["run_status"] = ("complete" if protocol["full_scope"] else "smoke_complete") if all_attempted and not errors else "incomplete_or_failed"
    except KeyboardInterrupt:
        metric["run_status"] = "interrupted"
        print("Interrupted. Use the download cell to keep the partial measurement.", flush=True)
    except Exception as error:
        metric["run_status"] = "failed"
        metric["error"] = type(error).__name__ + ": " + str(error)
        print(metric["error"], flush=True)
    finally:
        if image is not None:
            image.close()
        metric["measured_lines"] = len(records)
        metric["output_statuses"] = dict(Counter(r["status"] for r in records))
        metric["request_seconds_sum"] = sum(r["request_seconds"] for r in records)
        processing = metric.get("processing_seconds")
        metric["mean_seconds_per_line"] = processing/len(records) if processing and records else None
        page_count = len({r["printed_page"] for r in selected})
        full = metric["comparison_eligible"] and protocol["full_scope"]
        metric["mean_seconds_per_page_scope"] = processing/page_count if full and processing else None
        metric["page_scopes_per_hour"] = page_count*3600/processing if full and processing else None
        metric["page_scope_count"] = page_count
        export_clock = time.perf_counter()
        page_lookup = {p["printed_page"]: p for p in index["pages"]}
        _save_csv(directory / "lines.csv", [{"text": " ".join(r["raw_text"].split()),
                  "sources": page_lookup[r["printed_page"]]["source_page_url"]} for r in records], ["text", "sources"])
        _save_csv(directory / "pages.csv", page_records,
                  ["printed_page", "measured_lines", "selected_lines", "processing_seconds", "page_status"])
        metric["export_seconds"] = time.perf_counter()-export_clock
        if adapter is not None:
            try:
                memory_phases.append(gpu_allocated(adapter))
            except Exception as error:
                metric["allocator_error"] = str(error)
            try:
                adapter.close()
            except Exception as error:
                metric["cleanup_error"] = str(error)
        metric["framework_memory"] = {"gpu_peak_allocated_mib": max(
            (_mib(m["peak_allocated_bytes"]) for m in memory_phases if m.get("peak_allocated_bytes") is not None), default=None),
            "phases": memory_phases, "scope": "Framework allocator; load/warmup/process observed peaks. CPU engines: null."}
        if monitor is not None:
            try:
                metric["resources"] = monitor.stop()
            except Exception as error:
                metric["resources"] = {"error": str(error)}
        metric["run_wall_seconds"] = time.perf_counter()-clock
        ocr.write_json(directory / "metrics.json", metric)
        write_summary(root, protocol_id)
    return metric


"""Optional unified resource sampling; no OCR framework is imported here."""
import csv
import io
import platform
from pathlib import Path
import shutil
import subprocess
import threading
import time


def _cuda_api(adapter):
    device = str(getattr(adapter, "device", "cpu"))
    if not getattr(adapter, "gpu", device.startswith(("cuda", "gpu"))):
        return None
    framework = getattr(adapter, "framework", None)
    if framework is None:
        raise RuntimeError("GPU adapter exposes no framework for synchronization")
    return framework.device.cuda if getattr(adapter, "engine", "") == "paddleocr" else framework.cuda


def synchronize(adapter):
    """Synchronize the selected framework device before/after a timed GPU phase."""
    cuda = _cuda_api(adapter)
    if cuda is not None:
        cuda.synchronize()


def gpu_allocated(adapter, reset=False):
    """Framework allocator bytes, distinct from whole-device nvidia-smi usage."""
    cuda = _cuda_api(adapter)
    result = {"allocated_bytes": None, "peak_allocated_bytes": None,
              "reserved_bytes": None, "peak_reserved_bytes": None,
              "scope": "framework allocator; excludes driver and other processes"}
    if cuda is None:
        result["status"] = "not_used_cpu"
        return result
    errors = []
    if reset:
        resetters = (("reset_max_memory_allocated", "reset_max_memory_reserved")
                     if getattr(adapter, "engine", "") == "paddleocr" else ("reset_peak_memory_stats",))
        for name in resetters:
            method = getattr(cuda, name, None)
            if method:
                try:
                    method()
                except Exception as error:
                    errors.append(name + ": " + type(error).__name__)
    for key, name in (("allocated_bytes", "memory_allocated"),
                      ("peak_allocated_bytes", "max_memory_allocated"),
                      ("reserved_bytes", "memory_reserved"),
                      ("peak_reserved_bytes", "max_memory_reserved")):
        method = getattr(cuda, name, None)
        if method:
            try:
                result[key] = int(method())
            except Exception as error:
                errors.append(name + ": " + type(error).__name__)
    result.update(status="available" if result["allocated_bytes"] is not None else "unavailable", errors=errors)
    return result


class ResourceMonitor:
    """Self/reaped-child CPU deltas; process-tree RSS sampled every interval.

    RSS sums can double-count shared pages and miss short-lived child peaks.
    nvidia-smi values describe the entire selected GPU, not this process alone.
    """
    def __init__(self, device, engine, interval=.1, psutil_module=None, subprocess_runner=None):
        if interval <= 0:
            raise ValueError("Sampling interval must be positive")
        self.device, self.engine, self.interval = str(device), engine, float(interval)
        self._runner = subprocess_runner or subprocess.run
        self._event, self._lock = threading.Event(), threading.Lock()
        self._threads, self._result, self._errors = [], None, []
        self._peak_rss, self._rss_count, self._gpu_samples = None, 0, []
        self._use_gpu = self.device.startswith(("cuda", "gpu"))
        self._smi = shutil.which("nvidia-smi") or ("nvidia-smi" if subprocess_runner else None)
        self._gpu_status = ("not_used_cpu" if not self._use_gpu else
                            "pending_first_sample" if self._smi else "unavailable: nvidia-smi missing")
        self._psutil, self._process, self._resource = None, None, None
        self.hardware = {"cpu_logical_count": None, "cpu_model": platform.processor() or None,
                         "system_ram_total_bytes": None, "platform": platform.platform()}
        try:
            if psutil_module is None:
                import psutil as psutil_module
            self._psutil = psutil_module
            self._process = psutil_module.Process()
            self.hardware.update(cpu_logical_count=psutil_module.cpu_count(logical=True),
                                 system_ram_total_bytes=int(psutil_module.virtual_memory().total))
        except Exception as error:
            self._error("psutil", error)
        try:
            text = Path("/proc/cpuinfo").read_text()
            self.hardware["cpu_model"] = next((s.split(":", 1)[1].strip() for s in text.splitlines()
                                               if s.lower().startswith("model name")), self.hardware["cpu_model"])
        except OSError:
            pass
        try:
            import resource
            self._resource = resource
        except ImportError as error:
            self._error("resource", error)

    def _error(self, scope, error):
        message = scope + ": " + type(error).__name__ + ": " + str(error)[:140]
        with self._lock:
            if message not in self._errors and len(self._errors) < 5:
                self._errors.append(message)

    def _cpu(self):
        if self._resource is None:
            return None
        try:
            r = self._resource
            own, children = r.getrusage(r.RUSAGE_SELF), r.getrusage(r.RUSAGE_CHILDREN)
            return own.ru_utime + own.ru_stime, children.ru_utime + children.ru_stime
        except Exception as error:
            self._error("cpu", error)
            return None

    def _sample_rss(self):
        if self._process is None:
            return
        try:
            processes = [self._process] + self._process.children(recursive=True)
            total = 0
            for process in processes:
                try:
                    total += process.memory_info().rss
                except (self._psutil.NoSuchProcess, self._psutil.AccessDenied):
                    continue
            with self._lock:
                self._peak_rss = max(self._peak_rss or 0, int(total))
                self._rss_count += 1
        except Exception as error:
            self._error("rss", error)

    def _rss_loop(self):
        while not self._event.wait(self.interval):
            self._sample_rss()

    def _gpu_loop(self):
        command = [self._smi, "--id=0", "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                   "--format=csv,noheader,nounits"]
        while not self._event.is_set():
            try:
                response = self._runner(command, capture_output=True, text=True, timeout=2, check=True)
                row = next(csv.reader(io.StringIO(response.stdout)))
                if len(row) != 4:
                    raise ValueError("Unexpected GPU query output")
                def numeric(value):
                    try:
                        return float(value.strip())
                    except ValueError:
                        return None
                values = [numeric(value) for value in row[1:]]
                if not self._event.is_set():
                    with self._lock:
                        self._gpu_samples.append((row[0].strip(), *values))
                        self._gpu_status = "available"
            except Exception as error:
                self._gpu_status = "unavailable: " + type(error).__name__
                self._error("nvidia-smi", error)
                return
            if self._event.wait(max(1.0, self.interval)):
                return

    def start(self):
        if self._threads or hasattr(self, "_started"):
            raise RuntimeError("Create a new monitor for each measured run")
        self._started, self._cpu_start = time.perf_counter(), self._cpu()
        self._sample_rss()
        self._threads.append(threading.Thread(target=self._rss_loop, daemon=True))
        if self._use_gpu and self._smi:
            self._threads.append(threading.Thread(target=self._gpu_loop, daemon=True))
        for thread in self._threads:
            thread.start()
        return self

    def stop(self):
        if self._result is not None:
            return self._result
        if not hasattr(self, "_started"):
            raise RuntimeError("Start the monitor before stopping it")
        self._sample_rss()
        cpu_end, elapsed = self._cpu(), time.perf_counter() - self._started
        self._event.set()
        for thread in self._threads:
            thread.join(timeout=3)
        if self._gpu_status == "pending_first_sample":
            self._gpu_status = "no_sample_before_stop"
        own = child = None
        if self._cpu_start is not None and cpu_end is not None:
            own, child = [max(0.0, end - start) for start, end in zip(self._cpu_start, cpu_end)]
        used = [r[1] for r in self._gpu_samples if r[1] is not None]
        total = [r[2] for r in self._gpu_samples if r[2] is not None]
        util = [r[3] for r in self._gpu_samples if r[3] is not None]
        self._result = {**self.hardware, "monitor_wall_seconds": elapsed,
            "cpu_seconds_self": own, "cpu_seconds_reaped_children": child,
            "cpu_seconds_self_and_reaped_children": None if own is None else own + child,
            "cpu_utilization_percent_one_core": None if own is None or elapsed <= 0 else (own + child) / elapsed * 100,
            "peak_process_tree_rss_bytes_sampled": self._peak_rss, "rss_sample_count": self._rss_count,
            "rss_interval_seconds": self.interval, "gpu_monitor_status": self._gpu_status,
            "gpu_name": self._gpu_samples[-1][0] if self._gpu_samples else None,
            "gpu_total_memory_bytes": int(max(total) * 1024**2) if total else None,
            "gpu_peak_used_bytes_sampled": int(max(used) * 1024**2) if used else None,
            "gpu_utilization_percent_mean_sampled": sum(util)/len(util) if util else None,
            "gpu_utilization_percent_peak_sampled": max(util) if util else None,
            "gpu_sample_count": len(self._gpu_samples), "gpu_interval_seconds": max(1.0, self.interval),
            "scope": "CPU=self+reaped children (excludes alive/unreaped children); RSS=sum live process tree, sampled, shared pages may double count; GPU=whole device 0, sampled; monitor overhead included",
            "errors": list(self._errors)}
        return self._result



def build_notebook():
    """New notebook only; neither existing source nor existing notebook is edited."""
    import nbformat as nbf
    directory = Path(__file__).parent
    existing = json.loads((directory / "ocr_colab.ipynb").read_text())
    setup_cell = next(c for c in existing["cells"] if c.get("id") == "ocr-setup")
    setup = "".join(setup_cell["source"])
    expected = "dependencies = ['Pillow', 'numpy']"
    if setup.count(expected) != 1:
        raise ValueError("Existing setup changed; inspect before building the additive notebook")
    setup = "import time\n_METRIC_SETUP_START = time.perf_counter()\n" + setup.replace(
        expected, "dependencies = ['Pillow', 'numpy', 'psutil']")
    setup += "\nif ENGINE not in ('tesseract', 'paddleocr'):\n    import torch\n    DEVICE = 'cuda:0' if torch.cuda.is_available() else 'cpu'\n"
    setup += "SETUP_SECONDS = time.perf_counter() - _METRIC_SETUP_START\nprint('Measured setup seconds:', SETUP_SECONDS, '| actual device:', DEVICE)\n"
    cells = []
    def md(value):
        cells.append(nbf.v4.new_markdown_cell(value.strip()))
    def code(value, name, hidden=False):
        cell = nbf.v4.new_code_cell(value.strip())
        cell["id"] = "efficiency-" + name
        if hidden:
            cell.metadata.update({"cellView": "form", "collapsed": True, "jupyter": {"source_hidden": True}})
        cells.append(cell)
    md("""# BPL OCR · unified efficiency measurement

Use one model per **fresh hosted Colab runtime**. The existing OCR notebook, source scans and
results remain unchanged. This notebook runs **fresh inference**, including for models with
existing completed predictions. Existing results supply immutable model revisions only.

All five models receive identical original line crops, batch size 1, with one discarded warmup.
Default scope: 1,573 shared detections on pages 161–167; page 161 includes only its directory body.
Tesseract is measured as **line PSM 7**, with an engine process per line; historical page PSM 3
timings are a different condition. Device/precision settings follow the existing adapters.
""")
    md("""## 1. Choose a model and set up Colab

Edit `ENGINE`, then run both setup/helper cells. Reset the runtime before switching models.
Tesseract/Paddle use CPU; dots/Qwen require GPU; EasyOCR uses available CPU/GPU.
Setup seconds include dependency installation. Download plus model loading is measured separately.
""")
    code(setup, "setup")
    sources = {"ocr_pipeline.py": (directory / "ocr_pipeline.py").read_text(),
               "ocr_efficiency.py": Path(__file__).read_text()}
    code("_METRIC_SOURCES = " + repr(sources) + "\n"
         + "_CODE = Path('/content/bpl_efficiency_code')\n_CODE.mkdir(exist_ok=True)\n"
         + "for _name, _source in _METRIC_SOURCES.items():\n    (_CODE / _name).write_text(_source, encoding='utf-8')\n"
         + "sys.path.insert(0, str(_CODE))\n"
         + "from ocr_efficiency import import_efficiency_bundle, run_efficiency, pack_efficiency\n", "helpers", True)
    md("""## 2. Upload the existing final data ZIP

Upload a ZIP of `fa26/bpl_ocrs/`, or the latest efficiency ZIP from this notebook.
It contains `source/`, `results/`, and optionally `efficiency/`. Importing retains existing bytes;
only the new efficiency directory receives measurements. Browser upload time is excluded.
""")
    code("""from google.colab import files
uploaded = files.upload()
names = [name for name in uploaded if name.lower().endswith('.zip')]
if len(names) != 1:
    raise ValueError('Upload exactly one common final-results or efficiency ZIP.')
import_started = time.perf_counter()
uploaded_zip = Path('/content/bpl_efficiency_input.zip')
uploaded_zip.write_bytes(uploaded[names[0]])
ROOT = Path('/content/bpl_efficiency')
index = import_efficiency_bundle(uploaded_zip, ROOT)
IMPORT_SECONDS = time.perf_counter() - import_started
print('Seven pages loaded. Existing results retained.')
""", "inputs")
    md("""## 3. Measure fresh recognition

Keep `LINE_LIMIT = None` for the complete comparable measurement. Use `6` only for a smoke test;
smoke tests have a distinct protocol and no page-time estimate. Re-running measures again;
it does not reuse OCR predictions. Warmup is excluded from measured line counts.

Summary metrics include model load, processing, per-line/page averages, throughput, local export,
run wall time, CPU usage, sampled process-tree RAM (including Tesseract children), available
framework GPU allocator peaks, and sampled whole-device GPU memory/utilization.
Unavailable telemetry stays blank. CPU percent uses one logical core = 100% and may exceed 100%.
RAM/device samples may miss brief peaks; whole-device GPU readings include other processes.
CPU/GPU utilization averages cover loading through cleanup; line/page time covers processing only.

Processing includes page reads, crops, adapter preprocessing/inference/decode, GPU synchronization
and raw logging. Local export means writing this run's OCR CSVs, not ZIP/browser download.
Run wall time includes load/warmup/processing/export/cleanup, excluding setup, bundle import,
final metric serialization and ZIP transfer. No energy, monetary cost, FLOPs or accuracy is inferred.
""")
    code("""LINE_LIMIT = None  # 6 for a smoke test; None for all 1,573 source lines.
if ENGINE != _SETUP_ENGINE:
    raise RuntimeError('Reset the runtime before changing ENGINE.')
metrics = run_efficiency(ROOT, ENGINE, device=DEVICE, line_limit=LINE_LIMIT,
                         setup_seconds=SETUP_SECONDS, import_seconds=IMPORT_SECONDS)
print('Run status:', metrics['run_status'])
print((ROOT / 'efficiency/summary.csv').read_text(encoding='utf-8-sig'))
""", "run")
    md("""## 4. Download and continue with the next model

`efficiency/summary.csv` has one row per model and selects completed comparable measurements.
`not_measured` means that model still needs this fresh measurement. Each run retains detailed
settings, timing, telemetry, per-page records and exact new OCR responses under `efficiency/runs/`.
The original `results/lines.csv`, raw outputs and source images stay unchanged.

Download after completion or interruption. In a fresh runtime, select the next ENGINE and upload
this latest ZIP to accumulate all five rows. Use the same LINE_LIMIT for comparable results.
ZIP creation time is printed separately; browser transfer and ZIP time are outside run wall time.
""")
    code("""zip_started = time.perf_counter()
archive = pack_efficiency(ROOT, Path('/content/bpl_ocr_efficiency.zip'))
print('ZIP creation seconds (outside model run):', time.perf_counter() - zip_started)
files.download(str(archive))
""", "export")
    notebook = nbf.v4.new_notebook(cells=cells, metadata={
        "kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
        "language_info": {"name": "python"}, "accelerator": "GPU",
        "colab": {"name": "ocr_efficiency_colab.ipynb", "gpuType": "T4", "provenance": []}})
    nbf.validate(notebook)
    for cell in notebook.cells:
        if cell.cell_type == "code":
            compile(cell.source, cell.id, "exec")
    path = directory / "ocr_efficiency_colab.ipynb"
    nbf.write(notebook, path)
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notebook", action="store_true")
    parser.add_argument("--pack", type=Path)
    parser.add_argument("--output", type=Path, default=Path(tempfile.gettempdir()) / "bpl_ocr_efficiency.zip")
    args = parser.parse_args()
    if args.notebook:
        print(build_notebook())
    elif args.pack:
        print(pack_efficiency(args.pack, args.output))
    else:
        parser.print_help()
