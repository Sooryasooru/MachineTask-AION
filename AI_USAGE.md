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
- **Decided when to stop.** In week one I stopped tuning after the second run rather
  than fit my own test set, and left T-36's label unchanged after seeing it fail.

## What Claude did

- Wrote most of the code from my design: chunker, ingestion, retriever, refusal
  gates, LLM client, validator, pipeline, API, UI, eval scripts and tests
- Drafted the README and docs, which I corrected against what actually happened
- Wrote the script that listed candidate version conflicts, and helped diagnose
  failures from the eval traces

## Week two (after the first review)

- **I set the goal and the limits:** clean and honest, nothing heavy, no answer that
  passes today may break, and every change measured on questions frozen before it.
- **I decided what went:** the NLI checker, the benchmark script, unused report
  fields, and merging two small practice sets into one.
- **Holdout questions:** Claude drafted both holdout sets from the docs. I checked
  every expected answer against its source line in the corpus, then froze each set
  in its own commit before any code change it was meant to measure.
- **I kept the eval honest:** I ran each holdout's "after" measurement once, kept the
  fixes that came from reading holdout answers separate (and froze holdout2 for
  them), and chose not to chase the last incomplete answers with a prompt change that
  would re-run everything and use up the unseen set.
- **Claude wrote the code** for the retry, quote matching, stage notes, step timings,
  the request time limit and CI, and found the root causes in the traces (a passage
  cut at 1,000 characters, loosely copied quotes, italics in the docs). I applied each
  change, ran `make check` and every eval on my machine, and read the results.
