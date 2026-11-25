# Benchmarks

`bench_gpu.py` loads each local model (embedder, reranker, NLI) one at a time and writes what it cost to
`results/`. I ran it before settling the stack, because the laptop has about
7.4 GB of RAM and I didn't want to find out mid-build that the NLI model doesn't fit.

```bash
make bench
```

Each run saves a timestamped JSON file with the machine details and, per model,
load time, one inference time, peak VRAM and system RAM.

How I read it:

- All three load and peak VRAM stays well under the card's limit: keep all three on GPU.
- The NLI model fails or pushes VRAM close to the limit: move it to CPU, or drop it
  and use the reranker score as the support check.

API latency (p95) is measured separately by the eval run and reported in
`eval_report.json`.
