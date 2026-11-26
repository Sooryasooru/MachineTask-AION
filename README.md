# Kubernetes docs assistant (1.27 vs 1.31)

Ask a question about Kubernetes and get an answer built only from the official
docs for releases 1.27 and 1.31. Every claim cites the passage it came from, with
the exact words quoted. If the docs don't cover the question, it says so instead
of guessing. If the two releases disagree, it tells you what each one says.

## Run it

**Quickest: one command with Docker.** Unzip, then from the project folder:

```bash
LLM_API_KEY=your-groq-key docker compose up --build
```

The first build takes 10–20 minutes because it builds the search index inside the image. Then open http://localhost:8080. A free key comes from console.groq.com; you can also put it in a `.env` file instead.

**Without Docker** you need Python 3.12 and the same key:

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
make setup
cp .env.example .env      # add your key to LLM_API_KEY
make ingest               # builds the search index (~10 min on a laptop CPU)
make serve                # http://localhost:8080
```

Or with Docker, which builds the index inside the image:

```bash
make docker-build
make docker-run
```

Open **http://localhost:8080** to use the small web page. Each claim in an answer
has a 1.27 or 1.31 marker; click it to see the source passage with the quote
highlighted. The API itself:

```bash
curl -s localhost:8080/ask -H 'content-type: application/json' \
  -d '{"question": "How many minor versions may the kubelet lag behind kube-apiserver?"}'
```

Add `"version": "1.27"` or `"1.31"` to search only one release.

| Command | What it does |
|---|---|
| `make eval` | Runs my question set and writes `eval_report.json` |
| `make recall` | Measures retrieval on its own, for each search mode |
| `make smoke` | Runs the brief's edge cases against a running server |
| `make check` | Lint, type checks and 68 tests |

All settings are environment variables (see `.env.example`).

## The documents

From `github.com/kubernetes/website`, fetched 2026-11-25:

| Release | Branch | Commit | Pages |
|---|---|---|---|
| 1.27 | `release-1.27` | `f173f35` | 335 |
| 1.31 | `release-1.31` | `11f92a0` | 357 |

From each branch I took `content/en/docs/concepts/`, `content/en/docs/tasks/` and
`content/en/releases/version-skew-policy.md`. For 1.31 I also read the feature-gate
files, but only to look up whether a feature is alpha, beta or stable; they aren't
indexed as pages. The corpus is committed in `corpus/`, and `corpus/MANIFEST.json`
records the full commit hashes. `make fetch` pulls the same paths again.

## How it works

```
question
 → reject if empty, not English, or it names a flag/feature that doesn't exist
 → search each release separately (keyword + semantic, then rerank)
 → reject if nothing relevant was found
 → give the model the top passages from both releases, side by side
 → model drafts sentences, each with a quote from a passage
 → code checks every sentence; anything it can't verify is dropped
 → reject if nothing survives, otherwise return the answer with citations
```

The model never writes the final answer directly. It proposes sentences with
quotes, and code decides what stays. That's why every quote is guaranteed to be an
exact copy of the source text.

**Splitting the docs.** I split each page at its headings, because that's how the
docs are organised: one heading, one topic. Before splitting I turn Hugo's
template tags into real text using each release's own version number. Without
that step, the version skew page reads the same in both releases, which is
exactly the place they differ.

**Searching.** Each release is searched on its own, so one can't crowd the other
out of the results. Keyword search catches exact names like `--max-pods`; semantic
search catches meaning. Combining them found the right page for every question.

**Comparing releases.** This mattered most. My first run got only 3 of 9 version
questions right, because the 1.27 and 1.31 versions of the same section often
didn't both reach the model. Now every passage brings its twin from the other
release. That took it to 7 of 9.

**When it refuses.** There are three checks:
- *Unknown terms.* If the question names a flag or feature that appears nowhere in
  either release, it refuses straight away. This is checked against every term in
  the docs, not just the passages found.
- *Nothing relevant.* If the best search score is below 0.05, it refuses. I kept
  this low on purpose. Off-topic questions score near 0, but tricky unanswerable
  ones score almost as high as real ones (0.92 against 0.99), so no threshold can
  separate them without refusing good questions. Those are caught by the next check.
- *Nothing verified.* If no sentence the model writes can be backed by a quote, the
  answer becomes a refusal that explains what was missing.

**What I count as a hallucination:** any answer that isn't a refusal and is wrong,
either because it answered something it should have refused or because it got the
facts wrong. A refusal is never a hallucination; it counts as a false refusal, so
both kinds of mistake stay visible.

More detail: [architecture](docs/architecture.md), [evaluation method](docs/evaluation.md),
[decisions](docs/decisions.md).

## Results

My own laptop: HP Pavilion 14, 12th-gen Intel, 8 GB RAM, no GPU. The model was
`gpt-oss-120b` on Groq's free tier. Reproduce with `make ingest && make eval`.

| | Test (36 questions) | Written after first run (10) |
|---|---|---|
| Accuracy | **75%** | 80% |
| Unanswerable or false-premise questions refused | **100%** (11 of 11) | 100% (3 of 3) |
| Answerable questions wrongly refused | 24% | 29% |
| Hallucination rate | 8% | 0% |
| Version questions with both releases cited | **7 of 9** | 4 of 6 |
| Quotes that exactly match the source | **100%** | 100% |
| Right page found in top 5 (retrieval only) | **100%** | 100% |
| Slowest 5% of answers | 17 s | 15 s |

**How answers are scored.** Automatically, with no AI judge: a question that should be refused counts as correct only if it is refused with no citations; an answerable one only if the answer contains the expected facts, and for version questions names and cites both releases. Details in [docs/evaluation.md](docs/evaluation.md).

Answers usually take 2–5 seconds. The 17 s figure includes waiting on the free
tier's rate limit.

**Getting my exact numbers.** The model's replies from my run are saved in `eval/.llm_cache/`, so `make eval` replays them and reproduces every accuracy and refusal number above exactly, with no API key needed. Search, checking and scoring still run live on your machine; only latency differs, because no model calls are made. Delete that folder to run fresh with your own key, and expect small differences, because the model isn't perfectly deterministic.

**Being upfront:** I improved the system after seeing the first test run (63.9%
then). The changes were to the design, not thresholds tuned to my answers. To check
they hold up, I wrote 10 new questions before the second run, and those scored 80%.
The first run is kept in `eval/eval_report_v1_baseline.json`.

**Search on its own** (`make recall`): keyword alone and semantic alone each found
96% of the right pages; combined, 100%. The reranker added no recall, but it orders
the passages the model sees and gives the score behind the "nothing relevant"
check. My first reranker took 18.8 s per search on this laptop, so I switched to a
smaller one (1.2 s).

### The three answers it got most confidently wrong

1. **T-06, StatefulSet start ordinal.** It explained the 1.27 behaviour but dropped
   its own 1.31 sentence, so it never said the feature became stable. Nothing in it
   is false, which is what makes it the worst kind of wrong.
2. **T-07, KMS v1.** The sentence saying KMS v1 is deprecated in 1.31 had a quote
   that didn't match the source exactly, so it was dropped. The answer missed the
   one fact that mattered.
3. **T-36, pinning a Pod to a node.** Right in substance, but it didn't use the
   wording my scoring checks for. I left my expected answer as it was rather than
   change it after seeing the result.

None of the wrong answers came from search: the right page was always found. They
came from three places. The model sometimes paraphrased inside a quote, so the
check rejected it. The support check was too strict on some correct sentences. One
fact was cut off when passages were shortened for the model. Every one of these
fails safe: the system refused, it didn't make things up.

## Features

Everything the brief asks for, plus these extras:
- Combined keyword and semantic search, with measurements for each mode
- A reranker, with an honest note that it didn't add recall
- A `version` option to search one release
- A second set of questions written after seeing failures
- A web page where citations open their source passage

**Reliability.** `/readyz` reports whether the index and models actually loaded, and the Docker health check uses it. If the main model keeps failing, the service retries once with a smaller fallback model (`LLM_FALLBACK_MODEL`; switched off during `make eval` so the numbers come from one model). Each request writes one log line with its outcome and latency.

Every request gets a proper response, never a crash: an empty question, 4,000
characters, another language, broken JSON or the model being unavailable all
return the normal format. Rebuilding the index gives identical files every time.

## Known issues

- **It refuses too often.** About a quarter of answerable questions get refused,
  because the checks are strict. Showing the model full passages and asking for
  shorter quotes are the next things I'd try.
- **Half-answers on version questions.** If one release's sentence fails its
  check, the answer covers only the other release (T-06, T-07).
- **Absence statements have no citation.** A line like "The 1.27 documentation excerpts do not cover this" carries no `[chunk_id]`, because there is no passage to quote for something missing. Only that fixed form is allowed through without one.
- **Example files aren't included.** Some task pages point to YAML files I didn't
  ingest.
- **Free-tier limits.** Groq allows about one full eval run per day, which is one
  reason the recorded replies are included.

## What I left out

- **An AI judge for scoring.** Keyword checks are stricter, but anyone can
  reproduce my numbers exactly.
- **More tuning after the second run.** That would have meant fitting my own test
  questions.
- **The rest of the docs site.** Two bounded sections were enough to find real
  disagreements between releases.
- **A polished front end.** The page is one HTML file. My time went into making the
  answers right.

How I used AI on this project: [AI_USAGE.md](AI_USAGE.md).
