"""GPU runner for the same review crops used by the Tesseract notebook.

Uses the official dots-studio/dots.mocr checkpoint through Transformers. The
upstream vision module imports flash_attn unconditionally; a recorded import-only
compatibility edit permits its existing SDPA implementation on Colab GPUs.
No replacement model, made-up coordinates, or automatic spelling repair is used.
"""

import hashlib
from importlib.metadata import version as package_version
import json
from pathlib import Path
import time
from PIL import Image

# The same file is embedded after ocr_review.py in the standalone Colab notebook.
if "write_json" not in globals():
    from ocr_review import digest, image_digest, write_json


DOTS_PROMPT = (
    "Transcribe the printed text in this image in its original reading order. "
    "Keep each printed line separate. Preserve spelling, case, digits, punctuation, "
    "ditto marks, abbreviations and line-ending hyphens. Do not expand or correct the text. "
    "Return the transcription only, without explanations or Markdown fences."
)


def run_dots_units(root, manifest, model_id="dots-studio/dots.mocr", revision="main",
                   max_new_tokens=2048, max_pixels=1000000):
    import torch
    from huggingface_hub import HfApi, hf_hub_download, snapshot_download
    from transformers import AutoConfig, AutoModelForCausalLM, AutoProcessor
    from qwen_vl_utils import process_vision_info

    root = Path(root)
    if not torch.cuda.is_available():
        raise RuntimeError("Select a Colab GPU runtime, then rerun setup. CPU inference is not used here.")
    resolved_revision = HfApi().model_info(model_id, revision=revision).sha
    # A directory name without periods follows the project's documented workaround.
    local_model = root.parent / "DotsMOCR" / resolved_revision
    snapshot_download(repo_id=model_id, revision=resolved_revision, local_dir=str(local_model))
    hf_hub_download(repo_id=model_id, revision=resolved_revision, filename="modeling_dots_vision.py",
                    local_dir=str(local_model), force_download=True)
    vision_path = local_model / "modeling_dots_vision.py"
    original_source = vision_path.read_text(encoding="utf-8")
    original_hash = hashlib.sha256(original_source.encode()).hexdigest()
    unconditional = "from flash_attn import flash_attn_varlen_func"
    replacement = ("try:\n    from flash_attn import flash_attn_varlen_func\n"
                   "except ImportError:\n    flash_attn_varlen_func = None\n")
    if unconditional in original_source.splitlines():
        vision_path.write_text(original_source.replace(unconditional, replacement, 1), encoding="utf-8")
    if '"sdpa"' not in original_source and "'sdpa'" not in original_source:
        raise RuntimeError("This checkpoint no longer exposes the verified vision SDPA path; inspect upstream before running.")
    config = AutoConfig.from_pretrained(str(local_model), trust_remote_code=True)
    if isinstance(config.vision_config, dict):
        config.vision_config["attn_implementation"] = "sdpa"
    else:
        config.vision_config.attn_implementation = "sdpa"
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    runtime = {
        "model_id": model_id, "requested_revision": revision, "resolved_revision": resolved_revision,
        "gpu": torch.cuda.get_device_name(0), "dtype": str(dtype), "attention_backend": "sdpa",
        "compatibility_edit": "Guard the upstream unconditional flash_attn import; use the existing SDPA class. No weights changed.",
        "vision_code_original_sha256": original_hash,
        "vision_code_used_sha256": hashlib.sha256(vision_path.read_bytes()).hexdigest(),
        "prompt": DOTS_PROMPT, "do_sample": False, "max_new_tokens": max_new_tokens,
        "max_pixels": max_pixels, "units_sha256": manifest["units_sha256"],
        "packages": {name: package_version(name) for name in ["torch", "transformers", "accelerate", "qwen-vl-utils", "huggingface-hub"]},
        "runs": [],
    }
    # Persist dependency/code provenance before model loading, including failures.
    write_json(root / "ocr/dots_mocr_units/runtime.json", runtime)
    try:
        model = AutoModelForCausalLM.from_pretrained(
            str(local_model), config=config, trust_remote_code=True, torch_dtype=dtype,
            attn_implementation="sdpa", device_map={"": "cuda:0"}, low_cpu_mem_usage=True,
        ).eval()
        processor = AutoProcessor.from_pretrained(str(local_model), trust_remote_code=True)
    except Exception as error:
        runtime["load_error"] = type(error).__name__ + ": " + str(error)
        write_json(root / "ocr/dots_mocr_units/runtime.json", runtime)
        raise

    predictions = []
    aborted = False
    for unit in manifest["review_units"]:
        directory = root / "ocr/dots_mocr_units" / unit["unit_id"]
        directory.mkdir(parents=True, exist_ok=True)
        image_path = root / unit["image"]
        if image_digest(image_path) != unit["image_sha256"]:
            raise ValueError("Review input changed")
        text, status, note = "", "completed", "No generated word/line boxes are invented. Region is the actual input crop."
        record = {"unit_id": unit["unit_id"], "input_pixels_sha256": unit["image_sha256"],
                  "input_file_sha256": digest(image_path)}
        if aborted:
            status, note = "not_run", "An earlier unit ran out of GPU memory. Rerun on a suitable GPU."
        else:
            clock = time.perf_counter()
            try:
                messages = [{"role": "user", "content": [
                    {"type": "image", "image": str(image_path), "max_pixels": max_pixels},
                    {"type": "text", "text": DOTS_PROMPT},
                ]}]
                chat = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                images, videos = process_vision_info(messages)
                # Record what the model processor actually sees, including grid rounding.
                with Image.open(image_path) as original_image:
                    record["source_crop_size"] = list(original_image.size)
                record["vision_image_sizes"] = [list(image.size) for image in images]
                images[0].save(directory / "processor_input.png")
                inputs = processor(text=[chat], images=images, videos=videos, padding=True, return_tensors="pt").to("cuda")
                record["image_grid_thw"] = inputs["image_grid_thw"].tolist() if "image_grid_thw" in inputs else None
                torch.cuda.synchronize()
                with torch.inference_mode():
                    output = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
                torch.cuda.synchronize()
                generated = output[0, inputs.input_ids.shape[1]:]
                text = processor.decode(generated, skip_special_tokens=True, clean_up_tokenization_spaces=False)
                eos = model.generation_config.eos_token_id
                eos_ids = eos if isinstance(eos, list) else [eos]
                truncated = len(generated) >= max_new_tokens and (not len(generated) or int(generated[-1]) not in eos_ids)
                if truncated:
                    status, note = "truncated", "Token limit reached. Raw text retained; scoring treats the unit as failed until rerun."
                record["generated_tokens"] = len(generated)
                del inputs, output, generated
            except torch.cuda.OutOfMemoryError as error:
                status, note, aborted = "out_of_memory", str(error), True
                torch.cuda.empty_cache()
            except Exception as error:
                status, note = "failed", type(error).__name__ + ": " + str(error)
            record["seconds"] = round(time.perf_counter()-clock, 3)
        (directory / "raw.txt").write_text(text, encoding="utf-8")
        record.update(status=status, notes=note)
        write_json(directory / "run.json", record)
        runtime["runs"].append(record)
        write_json(root / "ocr/dots_mocr_units/runtime.json", runtime)
        predictions.append({"unit_id": unit["unit_id"], "method": "dots_mocr_units",
                            "input_mode": "same_review_crop_greedy_sdpa", "unit_image_sha256": unit["image_sha256"],
                            "text": text, "status": status, "notes": note})
        print("dots.mocr:", unit["unit_id"], status)
    del model
    torch.cuda.empty_cache()
    return predictions
