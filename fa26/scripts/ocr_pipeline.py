"""One BPL OCR pipeline: common scans/line geometry, five engines, line text only.

Hosted Colab runs recognition. Local CLI only builds the notebook or packages
the common data folder. No accuracy scoring, field extraction or gold labels.
"""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import time
import zipfile

FORMAT = "bpl-ocr-lines-v1"
ENGINES = ("tesseract", "dots_mocr", "easyocr", "paddleocr", "qwen3_vl_2b")
TEXT_FIELDS = ("tesseract_text", "mocr_text", "easyocr_text", "paddleocr_text", "qwen_text")
PAGES = list(range(161, 168))


def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sha_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def identity(value):
    return sha_text(json.dumps(value, sort_keys=True, ensure_ascii=False))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def source_identity(index):
    return identity({"pages": index["pages"], "lines": index["lines"], "scope": index["scope"]})


def load_sources(root):
    root = Path(root)
    index = json.loads((root / "source/index.json").read_text(encoding="utf-8"))
    if index.get("format") != FORMAT or [p["printed_page"] for p in index["pages"]] != PAGES:
        raise ValueError("Expected the common printed-page 161–167 source folder")
    if index.get("source_id") != source_identity(index):
        raise ValueError("Source metadata or shared line geometry changed")
    from PIL import Image
    pages = {p["printed_page"]: p for p in index["pages"]}
    for p in index["pages"]:
        if p["image"] != f"source/p{p['printed_page']}.jpg":
            raise ValueError("Unexpected source image path")
        image_path = root / p["image"]
        if sha_file(image_path) != p["sha256"]:
            raise ValueError("Source image changed: " + p["image"])
        with Image.open(image_path) as image:
            if list(image.size) != [p["width"], p["height"]]:
                raise ValueError("Source dimensions changed")
            image.verify()
    seen = set()
    for row in index["lines"]:
        page = pages[row["printed_page"]]
        x0, y0, x1, y1 = row["bbox"]
        if (row["line_id"] in seen or not (0 <= x0 < x1 <= page["width"] and 0 <= y0 < y1 <= page["height"])):
            raise ValueError("Duplicate line ID or invalid source coordinates")
        seen.add(row["line_id"])
    return index


def visible_lines(index):
    """Keep existing order; page 161 excludes the abbreviation key and footer."""
    return [r for r in index["lines"] if r["printed_page"] != 161 or 1645 <= r["bbox"][1] < 2678]


def line_identity(index, row):
    page = next(p for p in index["pages"] if p["printed_page"] == row["printed_page"])
    return identity({"source_sha256": page["sha256"], "line_id": row["line_id"], "bbox": row["bbox"]})


def read_jsonl(path):
    result = []
    if Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    result.append(value)
            except ValueError:
                pass  # Retain usable records when an interrupted append is incomplete.
    return result


def read_predictions(root, index, engine):
    if engine not in ENGINES:
        raise ValueError("Unknown engine")
    expected = {r["line_id"]: r for r in index["lines"]}
    models_path = Path(root) / "results/models.json"
    models = json.loads(models_path.read_text()) if models_path.exists() else {}
    metadata = models.get(engine, {})
    result = {}
    for record in read_jsonl(Path(root) / "results/raw" / (engine + ".jsonl")):
        row = expected.get(record.get("line_id"))
        text = record.get("raw_text")
        if row is None or not isinstance(text, str) or sha_text(text) != record.get("raw_text_sha256"):
            continue
        if record.get("input_id") is not None:
            matches = record["input_id"] == line_identity(index, row)
        else:
            # Native v4 mOCR log is preserved byte-for-byte during consolidation.
            matches = (metadata.get("imported_source_id") == index["source_id"]
                       and record.get("bbox") == row["bbox"])
        if matches and record.get("status") in ("completed", "empty", "failed", "truncated", "out_of_memory", "detected_no_text"):
            result[row["line_id"]] = record
    return result


def export_lines(root, index=None):
    root = Path(root)
    index = load_sources(root) if index is None else index
    predictions = {e: read_predictions(root, index, e) for e in ENGINES}
    pages = {p["printed_page"]: p for p in index["pages"]}
    path = root / "results/lines.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    counts = {}
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[*TEXT_FIELDS, "sources"])
        writer.writeheader()
        for row in visible_lines(index):
            out = {field: " ".join(predictions[e].get(row["line_id"], {}).get("raw_text", "").split())
                   for e, field in zip(ENGINES, TEXT_FIELDS)}
            out["sources"] = pages[row["printed_page"]]["source_page_url"]
            writer.writerow(out)
    for engine in ENGINES:
        counts[engine] = {status: sum(predictions[engine].get(r["line_id"], {}).get("status", "not_run") == status
                                     for r in visible_lines(index))
                          for status in ("completed", "empty", "failed", "truncated", "out_of_memory", "detected_no_text", "not_run")}
    write_json(root / "results/status.json", {"format": FORMAT, "source_id": index["source_id"],
               "rows": len(visible_lines(index)), "models": counts,
               "meaning": "One shared detected scan line per row, not one person. Blank text: inspect raw/status records. No accuracy measures."})
    return path


def import_bundle(archive, root):
    root = Path(root)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError("Output folder is populated. Continue with the loaded ROOT, or use a fresh Colab runtime.")
    with tempfile.TemporaryDirectory() as temporary:
        staging = Path(temporary) / "data"
        with zipfile.ZipFile(archive) as z:
            files = [i for i in z.infolist() if not i.is_dir() and not any(p.startswith(".") or p == "__MACOSX" for p in Path(i.filename).parts)]
            indexes = [i.filename for i in files if i.filename.endswith("source/index.json")]
            if len(indexes) != 1 or sum(i.file_size for i in files) > 500_000_000:
                raise ValueError("Upload one common BPL OCR folder ZIP (source/index.json required)")
            prefix = indexes[0][:-len("source/index.json")]
            for info in files:
                if not info.filename.startswith(prefix):
                    continue
                relative = Path(info.filename[len(prefix):])
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("Unsafe ZIP path")
                if (not relative.parts or relative.parts[0] not in ("source", "results")
                        or relative.suffix not in (".jpg", ".json", ".jsonl", ".csv", ".tsv", ".txt")):
                    continue
                if info.file_size > 100_000_000:
                    raise ValueError("ZIP member too large")
                target = staging / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(info))
        index = load_sources(staging)
        shutil.copytree(staging, root, dirs_exist_ok=True)
    export_lines(root, index)
    return index


def pack_bundle(root, destination):
    """Create an on-demand transfer ZIP; keep source images once in the workspace."""
    root, destination = Path(root), Path(destination)
    if root.resolve() in destination.resolve().parents:
        raise ValueError("Write the transfer ZIP outside the data folder")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        for directory in ("source", "results"):
            for path in sorted((root / directory).rglob("*")):
                if path.is_file() and not any(p.startswith(".") for p in path.relative_to(root).parts):
                    archive.write(path, path.relative_to(root))
    temporary.replace(destination)
    return destination


def run_ocr(root, engine, *, device="auto", max_new_lines=None, force=False, adapter_factory=None):
    """Append exact per-line outputs and checkpoint the same CSV for every model."""
    root = Path(root)
    if engine not in ENGINES:
        raise ValueError("Choose one of: " + ", ".join(ENGINES))
    if max_new_lines is not None and (type(max_new_lines) is not int or max_new_lines <= 0):
        raise ValueError("max_new_lines must be None or a positive integer")
    index = load_sources(root)
    lines = visible_lines(index)
    old = read_predictions(root, index, engine)
    pending = [r for r in lines if force or old.get(r["line_id"], {}).get("status") != "completed"]
    if max_new_lines is not None:
        pending = pending[:max_new_lines]
    print(engine, ":", len(lines), "source lines;", len(pending), "to recognize this run.", flush=True)
    if not pending:
        export_lines(root, index)
        return {"engine": engine, "new_lines": 0, "message": "Existing completed outputs retained; no model loaded."}
    models_path = root / "results/models.json"
    models = json.loads(models_path.read_text()) if models_path.exists() else {}
    prior = models.get(engine, {})
    pinned = prior.get("settings_history", {}).get(prior.get("active_settings_id"), {})
    adapter = (adapter_factory or build_recognizer)(engine, device=device, pinned_settings=pinned,
                                                   model_cache=root.parent / "bpl_ocr_model_cache")
    settings = {**adapter.settings, "pipeline_code_sha256": sha_file(__file__)}
    settings_id = identity(settings)
    history = dict(prior.get("settings_history", {}))
    history[settings_id] = settings
    models[engine] = {**prior, "active_settings_id": settings_id, "settings_history": history,
                      "last_runtime": adapter.metadata,
                      "input": "Shared original scan line crops. Existing imports retain their historical context in settings_history."}
    write_json(models_path, models)
    pages = {p["printed_page"]: p for p in index["pages"]}
    log_path = root / "results/raw" / (engine + ".jsonl")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    active_page, image, attempted = None, None, 0
    from PIL import Image
    try:
        with log_path.open("a", encoding="utf-8") as handle:
            if log_path.stat().st_size and not log_path.read_bytes().endswith(b"\n"):
                handle.write("\n")
            for row in pending:
                if active_page != row["printed_page"]:
                    if image is not None:
                        image.close()
                    page = pages[row["printed_page"]]
                    if sha_file(root / page["image"]) != page["sha256"]:
                        raise ValueError("Source image changed during OCR")
                    with Image.open(root / page["image"]) as source:
                        image = source.convert("RGB")
                    active_page = row["printed_page"]
                record = {"line_id": row["line_id"], "bbox": row["bbox"], "input_id": line_identity(index, row),
                          "settings_id": settings_id}
                try:
                    with image.crop(tuple(row["bbox"])) as tile:
                        result = adapter.predict(tile)
                    if not isinstance(result.get("raw_text"), str) or result.get("status") not in ("completed", "empty", "truncated"):
                        raise ValueError("Unexpected recognition response")
                    record.update(result)
                except Exception as error:
                    oom = "out of memory" in str(error).lower() or "outofmemory" in type(error).__name__.lower()
                    record.update(raw_text="", status="out_of_memory" if oom else "failed",
                                  error=type(error).__name__ + ": " + str(error))
                record["raw_text_sha256"] = sha_text(record["raw_text"])
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
                attempted += 1
                print(engine, row["line_id"], record["status"], f"({attempted}/{len(pending)})", flush=True)
                if attempted % 20 == 0:
                    export_lines(root, index)
                if record["status"] == "out_of_memory":
                    break
    except KeyboardInterrupt:
        print("Interrupted. Completed lines are saved. Run the download cell before leaving Colab.")
    finally:
        if image is not None:
            image.close()
        try:
            adapter.close()
        finally:
            export_lines(root, index)
    return {"engine": engine, "new_lines": attempted, "csv": str(root / "results/lines.csv")}


"""Recognition adapters for the common BPL line-image pipeline.

Only standard-library imports execute at import time. OCR frameworks and model
weights are loaded only by build_recognizer(), in the hosted Colab runtime.
Every recognizer sees the same original source crop, never another OCR's text.
"""
import base64
import gc
import hashlib
import importlib.metadata
import io
from pathlib import Path
import platform
import re
import shutil
import subprocess
import urllib.request

RECOGNIZER_KEYS = ("tesseract", "dots_mocr", "easyocr", "paddleocr", "qwen3_vl_2b")
TESSDATA_REVISION = "e12c65a915945e4c28e237a9b52bc4a8f39a0cec"
TESSDATA_SHA256 = "8280aed0782fe27257a68ea10fe7ef324ca0f8d85bd2fd145d1c2b560bcb66ba"
DOTS_REVISION = "e539fbb52280393adc081b289ec597430a0f9031"
DOTS_PROMPT = "Extract the text content from this image."


def _model_packages(*names):
    result = {}
    for name in names:
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = None
    return result


def _model_file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _model_revision(hub, repo, stored=None):
    revision = stored if stored is not None else hub.model_info(repo).sha
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Missing or invalid immutable model revision: " + repo)
    return revision


def _recognized(raw_text, **extra):
    return {"raw_text": raw_text, "status": "completed" if raw_text.strip() else "empty", **extra}


def _generation_result(raw, tokens, eos, limit):
    eos = eos if isinstance(eos, list) else [eos]
    truncated = len(tokens) >= limit and (not tokens or tokens[-1] not in eos)
    return {"raw_text": raw,
            "status": "truncated" if truncated else ("completed" if raw.strip() else "empty"),
            "extra": {"generated_tokens": len(tokens), "generated_token_ids": tokens}}


class _LineRecognizer:
    def __init__(self, engine, device, framework=None, packages=None):
        self.engine, self.device, self.framework = engine, device, framework
        self.gpu = device.startswith(("gpu", "cuda"))
        self.settings = {"engine": engine, "adapter_version": 1, "input": "one original RGB source-line crop",
                         "device_type": "cuda" if self.gpu else "cpu", "precision": "float32",
                         "packages": packages or {}}
        self.metadata = {"actual_device": device, "platform": platform.platform(),
                         "processor": platform.processor(), "packages": packages or {}}
        self.model = None

    def close(self):
        if self.engine == "paddleocr" and hasattr(self.model, "close"):
            self.model.close()
        self.model = None
        if hasattr(self, "processor"):
            self.processor = None
        gc.collect()
        if self.gpu:
            cuda = self.framework.device.cuda if self.engine == "paddleocr" else self.framework.cuda
            if hasattr(cuda, "empty_cache"):
                cuda.empty_cache()


class _TesseractRecognizer(_LineRecognizer):
    def __init__(self, model_cache):
        super().__init__("tesseract", "cpu", packages=_model_packages("Pillow"))
        self.binary = shutil.which("tesseract")
        if not self.binary:
            raise RuntimeError("Run the Colab Tesseract setup cell first")
        self.data_dir = Path(model_cache) / "tessdata_best" / TESSDATA_REVISION
        self.data_dir.mkdir(parents=True, exist_ok=True)
        target = self.data_dir / "eng.traineddata"
        if not target.exists() or _model_file_sha(target) != TESSDATA_SHA256:
            url = f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/{TESSDATA_REVISION}/eng.traineddata"
            request = urllib.request.Request(url, headers={"User-Agent": "BPL-OCR-Pipeline/1.0"})
            partial = target.with_suffix(".part")
            try:
                with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as handle:
                    shutil.copyfileobj(response, handle)
                if _model_file_sha(partial) != TESSDATA_SHA256:
                    raise ValueError("Pinned English Tesseract weights checksum mismatch")
                partial.replace(target)
            finally:
                partial.unlink(missing_ok=True)
        version = subprocess.run([self.binary, "--version"], capture_output=True, text=True, check=True).stdout.splitlines()[0]
        self.settings.update({"tesseract_version": version, "language": "eng", "oem": 1, "psm": 7,
                              "english_revision": TESSDATA_REVISION, "english_sha256": TESSDATA_SHA256,
                              "preprocessing": {"mode": "L", "scale": 2, "resampling": "LANCZOS", "white_border": 10}})

    def predict(self, image):
        from PIL import Image, ImageOps
        crop = image.convert("L")
        crop = crop.resize((crop.width*2, crop.height*2), Image.Resampling.LANCZOS)
        crop = ImageOps.expand(crop, border=10, fill=255)
        encoded = io.BytesIO()
        crop.save(encoded, format="PNG")
        result = subprocess.run([self.binary, "stdin", "stdout", "--tessdata-dir", str(self.data_dir),
                                 "-l", "eng", "--oem", "1", "--psm", "7"],
                                input=encoded.getvalue(), capture_output=True, check=True)
        return _recognized(result.stdout.decode("utf-8"), extra={"stderr": result.stderr.decode("utf-8", errors="replace")})


class _EasyRecognizer(_LineRecognizer):
    def __init__(self, device, torch, np, easyocr, model_cache):
        super().__init__("easyocr", device, torch, _model_packages("easyocr", "torch", "torchvision", "numpy", "Pillow"))
        self.np = np
        self.model = easyocr.Reader(["en"], gpu=device if self.gpu else False,
                                    detector=False, recog_network="english_g2", quantize=False,
                                    cudnn_benchmark=False, model_storage_directory=str(Path(model_cache) / "easyocr"))
        model_file = Path(self.model.model_storage_directory) / "english_g2.pth"
        self.settings.update({"recognizer": "english_g2", "languages": ["en"], "detector": False,
            "quantize": False, "cudnn_benchmark": False, "model_sha256": _model_file_sha(model_file),
            "recognition": {"decoder": "greedy", "batch_size": 1, "workers": 0, "detail": 1,
                            "paragraph": False, "contrast_ths": 0.1, "adjust_contrast": 0.5, "filter_ths": 0.003}})
        self.metadata["actual_device"] = str(self.model.device)
        if self.gpu:
            self.metadata["gpu_name"] = torch.cuda.get_device_name()

    def predict(self, image):
        predictions = self.model.recognize(self.np.asarray(image.convert("L")), **self.settings["recognition"])
        records = [{"polygon": [[float(x), float(y)] for x, y in box],
                    "text": str(text), "confidence": float(confidence)} for box, text, confidence in predictions]
        return _recognized("\n".join(r["text"] for r in records), extra={"recognition_results": records})


class _PaddleRecognizer(_LineRecognizer):
    def __init__(self, device, paddle, np, paddleocr, hub, pinned_settings=None):
        super().__init__("paddleocr", device, paddle,
                         _model_packages("paddleocr", "paddlex", "paddlepaddle", "paddlepaddle-gpu", "numpy", "Pillow"))
        self.np = np
        paddle.set_device(device)
        repo, name = "PaddlePaddle/en_PP-OCRv5_mobile_rec", "en_PP-OCRv5_mobile_rec"
        revision = _model_revision(hub, repo, (pinned_settings or {}).get("revision"))
        folder = Path(hub.snapshot_download(repo, revision=revision,
                      allow_patterns=["config.json", "inference.json", "inference.yml", "inference.pdiparams"]))
        hashes = {p.name: _model_file_sha(p) for p in sorted(folder.iterdir()) if p.is_file()}
        backend = {"enable_hpi": False, "engine": "paddle_static", "use_tensorrt": False,
                   "precision": "fp32", "enable_mkldnn": False, "cpu_threads": 2, "enable_cinn": False}
        self.model = paddleocr.TextRecognition(model_name=name, model_dir=str(folder), device=device, **backend)
        self.settings.update({"model": repo, "recognizer": name, "revision": revision,
                              "model_sha256": hashes, "input_channels": "BGR", "batch_size": 1, "backend": backend})
        self.metadata["actual_device"] = str(paddle.get_device())
        if self.gpu:
            self.metadata["gpu_name"] = paddle.device.cuda.get_device_name()

    def predict(self, image):
        bgr = self.np.asarray(image.convert("RGB"))[:, :, ::-1].copy()
        results = list(self.model.predict(input=bgr, batch_size=1))
        if len(results) != 1:
            raise ValueError("Expected one Paddle recognition result for one source crop")
        return _recognized(str(results[0]["rec_text"]), extra={"confidence": float(results[0]["rec_score"])})


class _QwenRecognizer(_LineRecognizer):
    def __init__(self, device, torch, transformers, hub, pinned_settings=None):
        super().__init__("qwen3_vl_2b", device, torch,
                         _model_packages("transformers", "torch", "torchvision", "accelerate", "numpy", "Pillow"))
        repo = "Qwen/Qwen3-VL-2B-Instruct"
        revision = _model_revision(hub, repo, (pinned_settings or {}).get("revision"))
        dtype = torch.float16 if self.gpu else torch.float32
        self.model = transformers.Qwen3VLForConditionalGeneration.from_pretrained(
            repo, revision=revision, dtype=dtype, attn_implementation="sdpa", device_map=device).eval()
        self.processor = transformers.AutoProcessor.from_pretrained(repo, revision=revision,
                             use_fast=False, min_pixels=4096, max_pixels=262144)
        prompt = ("Transcribe all text in this image faithfully. Preserve printed ditto marks, "
                  "abbreviations, punctuation and line breaks. Do not expand, correct, infer, "
                  "or explain anything. Output only the transcription.")
        self.settings.update({"model": repo, "revision": revision, "dtype": str(dtype),
            "precision": "float16" if self.gpu else "float32", "attention": "sdpa", "prompt": prompt,
            "min_pixels": 4096, "max_pixels": 262144,
            "generation": {"max_new_tokens": 256, "do_sample": False, "num_beams": 1, "repetition_penalty": 1.0},
            "processor_sha256": hashlib.sha256(self.processor.image_processor.to_json_string().encode()).hexdigest(),
            "generation_config": self.model.generation_config.to_dict()})
        if self.gpu:
            self.metadata["gpu_name"] = torch.cuda.get_device_name()

    def predict(self, image):
        messages = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": self.settings["prompt"]}]}]
        text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.processor(text=[text], images=[image.convert("RGB")], return_tensors="pt").to(self.model.device)
        inputs.pop("token_type_ids", None)
        with self.framework.inference_mode():
            generated = self.model.generate(**inputs, **self.settings["generation"])
        tokens = generated[0, inputs["input_ids"].shape[-1]:].tolist()
        raw = self.processor.decode(tokens, skip_special_tokens=True, clean_up_tokenization_spaces=False)
        return _generation_result(raw, tokens, self.model.generation_config.eos_token_id, 256)


class _DotsRecognizer(_LineRecognizer):
    def __init__(self, device, torch, transformers, hub, model_cache, pinned_settings=None):
        if not device.startswith("cuda"):
            raise RuntimeError("dots.mocr requires a Colab GPU runtime")
        super().__init__("dots_mocr", device, torch,
                         _model_packages("torch", "transformers", "qwen-vl-utils", "accelerate", "huggingface-hub", "Pillow"))
        repo = "dots-studio/dots.mocr"
        revision = _model_revision(hub, repo, (pinned_settings or {}).get("revision", DOTS_REVISION))
        local = Path(model_cache) / "dots_mocr" / revision
        hub.snapshot_download(repo, revision=revision, local_dir=str(local))
        hub.hf_hub_download(repo, "modeling_dots_vision.py", revision=revision, local_dir=str(local), force_download=True)
        vision_path = local / "modeling_dots_vision.py"
        source = vision_path.read_text()
        original_sha = hashlib.sha256(source.encode()).hexdigest()
        if '"sdpa"' not in source and "'sdpa'" not in source:
            raise RuntimeError("The pinned dots vision code lacks the expected SDPA implementation")
        guarded = "try:\n    from flash_attn import flash_attn_varlen_func\nexcept ImportError:\n    flash_attn_varlen_func = None\n"
        if "from flash_attn import flash_attn_varlen_func" in source.splitlines():
            vision_path.write_text(source.replace("from flash_attn import flash_attn_varlen_func", guarded, 1))
        config = transformers.AutoConfig.from_pretrained(str(local), trust_remote_code=True)
        if isinstance(config.vision_config, dict):
            config.vision_config["attn_implementation"] = "sdpa"
        else:
            config.vision_config.attn_implementation = "sdpa"
        self.model = transformers.AutoModelForCausalLM.from_pretrained(str(local), config=config,
            trust_remote_code=True, torch_dtype=torch.bfloat16, attn_implementation="sdpa",
            device_map={"": device}, low_cpu_mem_usage=True).eval()
        self.processor = transformers.AutoProcessor.from_pretrained(str(local), trust_remote_code=True)
        self.settings.update({"model": repo, "revision": revision, "prompt": DOTS_PROMPT,
            "dtype": "torch.bfloat16", "precision": "bfloat16", "attention": "sdpa", "max_pixels": 262144,
            "generation": {"max_new_tokens": 256, "do_sample": False},
            "original_vision_code_sha256": original_sha, "used_vision_code_sha256": _model_file_sha(vision_path)})
        self.metadata["gpu_name"] = torch.cuda.get_device_name()
        self.metadata["native_bfloat16_supported"] = bool(torch.cuda.is_bf16_supported())

    def predict(self, image):
        from qwen_vl_utils import process_vision_info
        encoded = io.BytesIO()
        image.save(encoded, format="PNG")
        data_url = "data:image/png;base64," + base64.b64encode(encoded.getvalue()).decode()
        messages = [{"role": "user", "content": [
            {"type": "image", "image": data_url, "max_pixels": 262144},
            {"type": "text", "text": DOTS_PROMPT}]}]
        chat = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        images, videos = process_vision_info(messages)
        inputs = self.processor(text=[chat], images=images, videos=videos, padding=True, return_tensors="pt").to(self.device)
        with self.framework.inference_mode():
            output = self.model.generate(**inputs, **self.settings["generation"])
        tokens = output[0, inputs.input_ids.shape[1]:].tolist()
        raw = self.processor.decode(tokens, skip_special_tokens=True, clean_up_tokenization_spaces=False)
        result = _generation_result(raw, tokens, self.model.generation_config.eos_token_id, 256)
        result["extra"]["processor_sizes"] = [list(im.size) for im in images]
        return result


def build_recognizer(engine, device="auto", pinned_settings=None, model_cache=None):
    """Load one recognition engine in hosted Colab; preserve immutable resume pins."""
    if engine not in RECOGNIZER_KEYS:
        raise ValueError("Unknown OCR engine: " + str(engine))
    if device not in {"auto", "cpu", "gpu", "gpu:0", "cuda", "cuda:0"}:
        raise ValueError("device must be auto, cpu or cuda:0")
    model_cache = Path(model_cache or "/content/bpl_model_cache")
    model_cache.mkdir(parents=True, exist_ok=True)
    if engine == "tesseract":
        return _TesseractRecognizer(model_cache)
    if engine == "paddleocr":
        import paddle
        import paddleocr
        import numpy as np
        import huggingface_hub as hub
        if device == "auto":
            device = "gpu:0" if paddle.is_compiled_with_cuda() and paddle.device.cuda.device_count() else "cpu"
        return _PaddleRecognizer("cpu" if device == "cpu" else "gpu:0", paddle, np, paddleocr, hub, pinned_settings)
    import torch
    if device == "auto":
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
    device = "cpu" if device == "cpu" else "cuda:0"
    if device != "cpu" and not torch.cuda.is_available():
        raise RuntimeError("A CUDA GPU was requested but is not available")
    if engine == "easyocr":
        import easyocr
        import numpy as np
        return _EasyRecognizer(device, torch, np, easyocr, model_cache)
    import transformers
    import huggingface_hub as hub
    if engine == "dots_mocr":
        return _DotsRecognizer(device, torch, transformers, hub, model_cache, pinned_settings)
    return _QwenRecognizer(device, torch, transformers, hub, pinned_settings)



def build_notebook():
    """Embed this exact shared file into the sole hosted Colab OCR notebook."""
    import nbformat as nbf
    source = Path(__file__).read_text(encoding="utf-8")
    cells = []
    def md(text):
        cells.append(nbf.v4.new_markdown_cell(text.strip()))
    def code(text, name):
        cell = nbf.v4.new_code_cell(text.strip())
        cell["id"] = "ocr-" + name
        cells.append(cell)
    md("""# BPL OCR · pages 161–167

One pipeline, the same seven scans and shared detected line coordinates, five selectable models.
Run one model in each **fresh hosted Colab runtime** and upload the latest data ZIP to accumulate outputs.
No local OCR installation or API key is required. The scope is OCR text only.

The supplied folder already includes the existing Tesseract and dots.mocr outputs.
Other model columns remain empty until run. Historical Tesseract text used full-page context;
fresh recognition in this notebook uses the same line crops as the other models.
One detected line is not necessarily one physical printed line or one person.
""")
    md("""## 1. Choose a model and set up Colab

Set `ENGINE` before running. Use GPU for dots.mocr and Qwen; EasyOCR uses an available GPU.
Tesseract and this PaddleOCR setup use CPU. Reset the runtime before changing the model.
""")
    code("""ENGINE = 'easyocr'  # tesseract, dots_mocr, easyocr, paddleocr, qwen3_vl_2b

import subprocess
import sys
from pathlib import Path

if not Path('/content').exists():
    raise RuntimeError('Use a hosted Google Colab runtime.')
if ENGINE not in ('tesseract', 'dots_mocr', 'easyocr', 'paddleocr', 'qwen3_vl_2b'):
    raise ValueError('Choose one of the five documented model names.')
if '_SETUP_ENGINE' in globals() and ENGINE != _SETUP_ENGINE:
    raise RuntimeError('Reset the runtime before changing ENGINE.')
dependencies = ['Pillow', 'numpy']
if ENGINE == 'tesseract':
    subprocess.run(['apt-get', 'update', '-qq'], check=True)
    subprocess.run(['apt-get', 'install', '-y', '-qq', 'tesseract-ocr'], check=True)
elif ENGINE == 'easyocr':
    dependencies += ['easyocr==1.7.2']
elif ENGINE == 'paddleocr':
    dependencies += ['paddlepaddle==3.2.0', 'paddleocr==3.7.0', 'huggingface-hub==0.36.2']
else:
    dependencies += ['transformers==4.57.6', 'accelerate==1.15.0', 'huggingface-hub==0.36.2']
    if ENGINE == 'dots_mocr':
        dependencies += ['qwen-vl-utils==0.0.14']
subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '--disable-pip-version-check', *dependencies], check=True)
DEVICE = 'cpu' if ENGINE in ('tesseract', 'paddleocr') else 'auto'
if ENGINE in ('dots_mocr', 'qwen3_vl_2b'):
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError('Select Runtime > Change runtime type > GPU.')
_SETUP_ENGINE = ENGINE
print('Selected:', ENGINE, '| device:', DEVICE)
""", "setup")
    code("# Exact shared ocr_pipeline.py; no repository checkout is needed.\n"
         + "_PIPELINE_SOURCE = " + repr(source) + "\n"
         + "_CODE = Path('/content/bpl_ocr_code')\n_CODE.mkdir(exist_ok=True)\n"
         + "(_CODE / 'ocr_pipeline.py').write_text(_PIPELINE_SOURCE, encoding='utf-8')\n"
         + "sys.path.insert(0, str(_CODE))\n"
         + "from ocr_pipeline import import_bundle, run_ocr, export_lines, pack_bundle\n", "helpers")
    md("""## 2. Upload the common source/results ZIP

Upload a ZIP of the common `fa26/data/ocr/` folder, or the latest ZIP downloaded below.
It contains `source/` and `results/`. Seven scans are kept once; line crops exist in memory only.
The existing coordinates are shared by all models, including any detection mistakes.
Page 161 uses its lower directory body; pages 162–167 retain their existing detected lines.
""")
    code("""from google.colab import files
uploaded = files.upload()
archives = [name for name in uploaded if name.lower().endswith('.zip')]
if len(archives) != 1:
    raise ValueError('Upload exactly one common source/results ZIP.')
uploaded_zip = Path('/content/bpl_uploaded.zip')
uploaded_zip.write_bytes(uploaded[archives[0]])
ROOT = Path('/content/bpl_ocr')
index = import_bundle(uploaded_zip, ROOT)
print('Loaded seven pages. CSV:', ROOT / 'results/lines.csv')
""", "inputs")
    md("""## 3. Recognize lines

`MAX_NEW_LINES = None` processes all remaining target lines; use `6` for a quick smoke test.
Completed outputs are retained by default, so existing Tesseract/mOCR results need no rerun.
Empty/failed/truncated outputs are retried. `FORCE = True` re-recognizes target lines;
earlier raw responses and their original settings remain in the log.

Every model receives only the original line image. No other OCR text, name list or corrections
enter recognition. Printed ditto marks and abbreviations are kept as recognized.
Interrupt the cell if necessary, then run section 4 to download a checkpoint.
""")
    code("""MAX_NEW_LINES = None  # Set 6 for a short trial.
FORCE = False
if ENGINE != _SETUP_ENGINE:
    raise RuntimeError('Reset the runtime before changing ENGINE.')
summary = run_ocr(ROOT, ENGINE, device=DEVICE, max_new_lines=MAX_NEW_LINES, force=FORCE)
print(summary)
""", "run")
    md("""## 4. Download the same output folder

`results/lines.csv` contains only the five model text columns and `sources`.
Blank cells mean no available output; internal status/raw records distinguish unrun and failed cases.
It preserves one row per shared detected line, including failures. It does not join people or parse fields.

The ZIP also retains original scans, shared coordinates and raw outputs for resuming.
Upload this latest ZIP in a fresh runtime for the next model. Download before Colab discards the VM.
""")
    code("""csv_path = export_lines(ROOT)
archive = pack_bundle(ROOT, Path('/content/bpl_ocr.zip'))
print('Line output:', csv_path)
files.download(str(archive))
""", "export")
    notebook = nbf.v4.new_notebook(cells=cells, metadata={
        "kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
        "language_info": {"name": "python"}, "accelerator": "GPU",
        "colab": {"name": "ocr_colab.ipynb", "gpuType": "T4", "provenance": []}})
    nbf.validate(notebook)
    target = Path(__file__).with_name("ocr_colab.ipynb")
    nbf.write(notebook, target)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notebook", action="store_true", help="Regenerate the single Colab notebook")
    parser.add_argument("--pack", type=Path, help="Common source/results folder to package")
    parser.add_argument("--output", type=Path, default=Path(tempfile.gettempdir()) / "bpl_ocr.zip")
    args = parser.parse_args()
    if args.notebook:
        print(build_notebook())
    elif args.pack:
        print(pack_bundle(args.pack, args.output))
    else:
        parser.print_help()
