# Note on AI-assisted work

I built this with Claude (Anthropic) as a pair programmer. In short: I owned the
requirements, the design decisions and the testing; Claude wrote most of the code.

## What I did

- **Understood the requirements.** I broke the brief down into what is actually
  scored (refusal, citation integrity, version handling, honest numbers) and planned
  the work in two parts around that, inside the time box.
- **Owned the system design.** Claude proposed options; I chose between them and
  corrected the plan where it was weak. The main calls were mine:
  - retrieve each release independently, then pair results by `doc_id`
  - check false premises against the whole corpus, not just what was retrieved
  - add a semantic (NLI) support check next to exact-quote matching, and drop
    unsupported claims instead of repairing quotes (after an outside review of
    run 2, I ablated NLI and switched it off, and allowed near-verbatim quotes to
    align to the real text)
  - keep dev and test strictly apart, and report the post-failure slice separately
- **Compared the tools before committing.** Embedding models, vector stores, LLM
  providers and rerankers. I benchmarked the models on my own laptop first, and that
  led to going CPU-only (no NVIDIA GPU) and swapping the reranker when the
  measurements showed it was too slow.
- **Ran, tested and debugged everything.** Every ingest, eval and Docker run happened
  on my machine. I read each output before moving on, found the failures, and worked
  through the fixes: a double sigmoid on reranker scores, Hugo anchors left in
  headings, a stale `.env`, a model Groq had retired mid-build, and the one-version
  answers that the first eval run exposed.
- **Reviewed the eval set.** I read the release pairs side by side, checked that each
  version conflict is real, and decided which questions to keep.
- **Decided when to stop.** I stopped tuning after the second run rather than fit my
  own test set, and left T-36's label unchanged after seeing it fail.

## What Claude did

- Wrote most of the code from my design: chunker, ingestion, retriever, refusal
  gates, LLM client, validator, pipeline, API, UI, eval scripts and tests
- Drafted the README and docs, which I corrected against what actually happened
- Wrote the script that listed candidate version conflicts, and helped diagnose
  failures from the eval traces
