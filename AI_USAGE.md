# Note on AI-assisted work

I used Claude (Anthropic) throughout this assignment as a pair programmer. This is
an honest split of what came from where.

## Mostly AI-generated, reviewed and run by me

- The first drafts of almost all the code: project scaffold, chunker, ingestion,
  retriever, refusal gates, LLM client, validator, pipeline, API, evaluation scripts
  and the tests
- First drafts of the README and the docs, which I then went through and corrected
  against what actually happened on my machine
- The script that compared `FEATURE STATE` lines across releases to list candidate
  version conflicts

## My own work

- Running everything on my own laptop: setting up the environment, benchmarking
  the models, fetching the corpus, every ingest and eval run, and reading the output
  of each step before moving on
- Design corrections I made when reviewing the AI's plan:
  - retrieve each release independently before combining
  - pair releases by `doc_id`, not chunk position
  - check false premises against the whole corpus, not just the retrieved chunks
  - add a semantic support check next to the exact-quote check, and drop unsupported
    claims rather than repairing quotes
  - verify GPU and RAM before committing to a model stack
  - specify a small local fallback model
  - keep dev and test strictly apart, and report the post-failure slice separately
- Reviewing the eval questions: reading the release pairs side by side, checking
  that each conflict is real, and deciding which questions to keep
- Decisions during the build: going CPU-only after finding there was no NVIDIA
  GPU, switching models when Groq retired the planned one, stopping tuning after
  run 2 instead of fitting the test set, and keeping T-36's label unchanged
- Reading the traces and agreeing the failure analysis

Where the AI drafted something, I ran it, checked the output and asked for changes
when it was wrong. Several bugs were found that way: a double sigmoid on reranker
scores, Hugo anchors left in headings, a stale `.env`, and the retired model.
