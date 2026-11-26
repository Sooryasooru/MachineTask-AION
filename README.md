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

The first build takes 10–20 minutes because it builds the search index inside the
image. Then open http://localhost:8080. A free key comes from console.groq.com; you
can also put it in a `.env` file instead.

**Without Docker** you need Python 3.12 and the same key:

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu
make setup
cp .env.example .env      # add your key to LLM_API_KEY
make ingest               # builds the search index (~10 min on a laptop CPU)
make serve                # http://localhost:8080
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
| `make check` | Lint, type checks and tests |

All settings are environment variables (see `.env.example`), and dependencies are
pinned to the versions the numbers below were measured with.

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
 → reject if empty, not English, or it names a flag or feature gate that doesn't exist
 → search each release separately (keyword + semantic, then rerank)
 → reject if nothing relevant was found
 → give the model the top passages from both releases, side by side
 → model drafts sentences, each with a quote from a passage
 → code checks every sentence; anything it can't verify is dropped
 → if only one release made it through, code adds the other release's feature state
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
release. On top of that, if an answer still covers only one release, code reads the
`FEATURE STATE` line from the other release's twin section and adds it, quoted and
cited. Nothing in that step is generated, so it can't be invented.

**Checking each sentence.** A sentence survives only if its quote really is in the
cited passage, and every number and maturity word (alpha, beta, stable, deprecated)
it states appears there too. When the model's quote is nearly but not exactly
verbatim (a dropped word, two lines joined), it's aligned to the closest real span,
but only if it's at least 90% similar and states the same numbers and stages. The
quote returned is always the passage's own text.

**When it refuses.** There are three checks:
- *Unknown terms.* If the question names a `--flag` or a feature gate that appears
  nowhere in either release, it refuses straight away. This is checked against
  every term in the docs, not just the passages found.
- *Nothing relevant.* If the best search score is below 0.05, it refuses. I kept
  this low on purpose. Off-topic questions score near 0, but tricky unanswerable
  ones score almost as high as real ones (0.92 against 0.99), so no threshold can
  separate them without refusing good questions. Those are caught by the next check.
- *Nothing verified.* If no sentence the model writes can be backed by a quote, the
  answer becomes a refusal that explains what was missing.

**What I count as a hallucination:** any answer that isn't a refusal and is wrong,
either because it answered something it should have refused or because it missed
a fact the expected answer requires. The report shows the two parts separately. A
refusal is never a hallucination; it counts as a false refusal, so both kinds of
mistake stay visible.

More detail: [architecture](docs/architecture.md), [evaluation method](docs/evaluation.md),
[decisions](docs/decisions.md).

## Results

My own laptop: HP Pavilion 14, 12th-gen Intel, 8 GB RAM, no GPU. The model was
`gpt-oss-120b` on Groq's free tier. Reproduce with `make ingest && make eval`.

| | Test (36 questions) | Dev (10) | Written after first run (10) |
|---|---|---|---|
| Accuracy | **86.1%** | 80.0% | 100% |
| Unanswerable or false-premise questions refused | **100%** (11 of 11) | 100% (3 of 3) | 100% (3 of 3) |
| Answerable questions wrongly refused | **8%** | 14% | 0% |
| Hallucination rate (all were incomplete, none answered what it should refuse) | 8.3% | 10.0% | 0% |
| Version questions with both releases cited | **8 of 9** | 2 of 2 | 6 of 6 |
| Quotes that exactly match the source | **100%** | 100% | 100% |
| Right page found in top 5 (retrieval only) | **100%** | 100% | 100% |

**How answers are scored.** Automatically, with no AI judge: a question that should
be refused counts as correct only if it is refused with no citations; an answerable
one only if the answer contains the expected facts, and for version questions names
and cites both releases. Details in [docs/evaluation.md](docs/evaluation.md).

**Latency.** Live, answers take 2–5 seconds and the slowest 5% took 17 s, which
includes waiting on the free tier's rate limit (`eval/eval_report_run2_live.json`).
The committed `eval_report.json` is a replay of recorded model replies (see below),
so its latency leaves out the model call; the report says so in `llm_replies`.

**Getting my exact numbers.** The model's replies are saved in `eval/.llm_cache/`,
so `make eval` replays them and reproduces every number above exactly, with no API
key needed. Search, checking and scoring still run live on your machine. Delete
that folder to run fresh with your own key, and expect small differences, because
the model isn't perfectly deterministic.

### How the numbers got here, stated plainly

| Test set | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| Accuracy | 63.9% | 75.0% | **86.1%** |
| Version conflicts | 3/9 | 7/9 | **8/9** |
| Wrongly refused | 28% | 24% | **8%** |
| Unanswerable refused | 11/11 | 11/11 | 11/11 |

- **Run 1 → 2:** design changes after reading the first run's traces (twin passages
  from both releases, a better support check). I wrote the 10 "after first run"
  questions *before* run 2 to check the fixes held up; they scored 80% then.
- **Run 2 → 3:** changes after an outside review of run 2: quote alignment, adding
  the other release's feature state in code, a narrower unknown-term check, and
  switching off the NLI support check (next section). Run 3 uses **exactly the same
  model replies as run 2**; only the checking after the model changed. Because these
  changes came after seeing failures on every set, including the "after first run"
  slice, no set is unseen any more. The 10 held-out questions you pose are the real
  test.

Runs 1 and 2 are kept in `eval/eval_report_v1_baseline.json` and
`eval/eval_report_run2_live.json`.

### The NLI ablation, and how I decided

The NLI model was a second support check on every sentence. I replayed the same
replies with it on and off:

| Test set | NLI on | NLI off |
|---|---|---|
| Accuracy | 77.8% | 86.1% |
| Wrongly refused | 24% | 8% |
| Answered but incomplete | 2 | 3 |
| Answered what should be refused | 0 | 0 |

Before measuring, my rule was to keep NLI only if it stopped wrong answers getting
through. Taken literally, it did: one more incomplete answer appears without it
(T-35). I then read that answer. It's correct (create an `EncryptionConfiguration`,
restart the API server) and fully quoted; it only leaves out the flag name the
scoring looks for. So NLI's only real effect was refusing good answers, and it is
now off by default (`NLI_ENABLED=true` turns it back on). I'm stating this because
the decision was made after looking at that answer, not purely by the rule.

**Search on its own** (`make recall`): keyword alone and semantic alone each found
96% of the right pages; combined, 100%. The reranker added no recall, but it orders
the passages the model sees and gives the score behind the "nothing relevant" check.
My first reranker took 18.8 s per search on this laptop, so I switched to a smaller
one (1.2 s).

### The three answers it gets most confidently wrong

1. **T-07, KMS v1.** It answers for 1.27 (use KMS v2 for better performance) but
   never says that 1.31 deprecated KMS v1, the one fact that matters. The 1.31
   sentence failed its check, and the twin section had no different feature state
   for code to add.
2. **T-35, encryption at rest.** Correct and quoted, but it doesn't name
   `--encryption-provider-config`, which the expected answer requires.
3. **T-36, pinning a Pod to a node.** Right in substance (label the node, use
   `nodeSelector`), but cites the DaemonSet page and doesn't say `kubectl label`. I
   left my expected answer as it was rather than change it after seeing the result.

None of the wrong answers came from search: the right page was always found.

## Features

Everything the brief asks for, plus these extras:
- Combined keyword and semantic search, with measurements for each mode
- A reranker, with an honest note that it didn't add recall
- A `version` option to search one release
- A second set of questions written after seeing failures
- A web page where citations open their source passage

**Reliability.** `/readyz` reports whether the index and models actually loaded,
and the Docker health check uses it. If the main model keeps failing, the service
retries once with a smaller fallback model (`LLM_FALLBACK_MODEL`; switched off
during `make eval` so the numbers come from one model). Each request writes one log
line with its outcome and latency.

Every request gets a proper response, never a crash: an empty question, 4,000
characters, another language, broken JSON or the model being unavailable all
return the normal format. Rebuilding the index gives identical files every time.

## Known issues

- **One-sided version answers can still happen.** T-07 covers only 1.27. Code only
  fills in the other release when its twin section states a different feature state.
- **Absence statements have no citation.** A line like "The 1.27 documentation
  excerpts do not cover this" carries no `[chunk_id]`, because there is no passage
  to quote for something missing. Only that fixed form is allowed through without one.
- **My version questions lean on feature-state changes.** 8 of 9 are maturity
  differences, found by comparing `FEATURE STATE` lines, and T-01 is the brief's own
  example. Conflicts in defaults, removed flags and renamed fields would test more.
- **Scoring is keyword-based.** It's reproducible, but stricter than a human reader
  (T-35, T-36).
- **Example files aren't included.** Some task pages point to YAML files I didn't
  ingest.
- **Free-tier limits.** Groq allows only about one full live eval run per day, which
  is one reason the recorded replies are included.

## Next steps I didn't get to

These came out of the review of run 2 and need fresh model calls, so they wait on
the free tier's daily quota:
- Show the model full passages instead of the first 1,000 characters (T-28's answer
  sits past that cut).
- When every sentence fails its check on a strongly matched question, ask the model
  once more, telling it which quotes didn't match.
- Add version questions found by reading: changed defaults, removed flags, renamed
  fields.
- Commit a fresh live run, so latency and accuracy come from the same report.

## What I left out

- **An AI judge for scoring.** Keyword checks are stricter, but anyone can
  reproduce my numbers exactly.
- **The rest of the docs site.** Two bounded sections were enough to find real
  disagreements between releases.
- **A polished front end.** The page is one HTML file. My time went into making the
  answers right.

How I used AI on this project: [AI_USAGE.md](AI_USAGE.md).
