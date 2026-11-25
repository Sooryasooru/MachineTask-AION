"""Checks whether the three local models fit on this machine.

Loads each model on its own, runs one small inference, and records load time,
inference time, peak VRAM and system RAM. Results go to benchmarks/results/.

Run: make bench
"""

from __future__ import annotations

import gc
import json
import platform
import time
from datetime import datetime
from pathlib import Path

import psutil
import torch
from sentence_transformers import CrossEncoder, SentenceTransformer

MODELS = [
    ("embedder", "BAAI/bge-small-en-v1.5", "bi"),
    ("reranker", "BAAI/bge-reranker-base", "cross"),
    ("nli", "cross-encoder/nli-deberta-v3-small", "cross"),
]
SAMPLE_Q = "How many minor versions may the kubelet lag behind kube-apiserver?"
SAMPLE_DOC = "The kubelet may be up to three minor versions older than kube-apiserver."
RESULTS_DIR = Path(__file__).parent / "results"


def gb(n_bytes: float) -> float:
    """Bytes to gigabytes, rounded for reading."""
    return round(n_bytes / 1e9, 2)


def bench_one(name: str, model_id: str, kind: str, device: str) -> dict:
    """Load one model, run a single inference, report the cost."""
    if device == "cuda":
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

    start = time.perf_counter()
    if kind == "bi":
        model = SentenceTransformer(model_id, device=device)
        if device == "cuda":
            model.half()
    else:
        model = CrossEncoder(model_id, device=device)
        if device == "cuda":
            model.model.half()
    load_s = time.perf_counter() - start

    start = time.perf_counter()
    if kind == "bi":
        model.encode([SAMPLE_Q, SAMPLE_DOC])
    else:
        model.predict([(SAMPLE_Q, SAMPLE_DOC)])
    infer_ms = (time.perf_counter() - start) * 1000

    row = {
        "model": name,
        "id": model_id,
        "load_s": round(load_s, 1),
        "infer_ms": round(infer_ms, 1),
        "peak_vram_gb": gb(torch.cuda.max_memory_allocated()) if device == "cuda" else 0.0,
        "ram_used_gb": gb(psutil.virtual_memory().used),
    }
    del model
    gc.collect()
    return row


def main() -> None:
    """Run every model and save one JSON file per run."""
    has_cuda = torch.cuda.is_available()
    device = "cuda" if has_cuda else "cpu"
    machine = {
        "os": platform.platform(),
        "python": platform.python_version(),
        "torch": torch.__version__,
        "ram_total_gb": gb(psutil.virtual_memory().total),
        "gpu": torch.cuda.get_device_name(0) if has_cuda else None,
        "vram_total_gb": gb(torch.cuda.get_device_properties(0).total_memory) if has_cuda else 0.0,
    }
    print(json.dumps(machine, indent=2))
    if not has_cuda:
        print("No CUDA device found, so this run is on CPU.")

    rows = []
    for name, model_id, kind in MODELS:
        try:
            row = bench_one(name, model_id, kind, device)
        except RuntimeError as err:  # out of memory lands here
            row = {"model": name, "id": model_id, "error": str(err)[:200]}
        rows.append(row)
        print(row)

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"gpu_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps({"machine": machine, "models": rows}, indent=2))
    print(f"Saved to {out}")


if __name__ == "__main__":
    main()
