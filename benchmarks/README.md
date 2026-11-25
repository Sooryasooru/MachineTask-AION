### Model Benchmarking

Before finalizing the stack, `bench_gpu.py` tests each model (embedding, reranker and NLI) individually to check memory usage and performance.

```bash
make bench
```

Each run saves a timestamped JSON report in `results/` with load time, inference time, peak VRAM and RAM usage.

If all models fit comfortably, they stay on GPU. Otherwise, NLI moves to CPU or is dropped in favour of reranker-based scoring.

API p95 latency is measured separately during evaluation and saved in `eval_report.json`.
