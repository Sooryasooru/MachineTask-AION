# Grounded documentation assistant: Kubernetes 1.27 vs 1.31

A question-answering service over two releases of the Kubernetes docs. Every
answer carries inline `[chunk_id]` citations with verbatim quotes. It refuses when
the docs don't cover a question, and it names both releases when they disagree.

The short version of how it went: the first full run scored 63.9% on my test set
and handled only 3 of 9 version conflicts. The traces showed why (more on that
below), I fixed the cause rather than the symptoms, and the second run scored
75.0% with 7 of 9 conflicts. A slice of new questions written after that first
run scored 80%. The system still refuses some questions it could have answered.
That's the main weakness, and it's written up honestly further down.

---

## Running it from a clean machine

Tested on Ubuntu 24.04 with Python 3.12, CPU only.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
make setup                 # dev dependencies
cp .env.example .env       # then put a Groq key in LLM_API_KEY (free at console.groq.com)
make fetch                 # pull the two doc releases into corpus/ (already committed)
make ingest                # build index/ from corpus/ (about 10 min on a laptop CPU)
make serve                 # http://localhost:8080
make eval                  # writes eval_report.json
```

Or with Docker (CPU image; the index is built during the image build):

```bash
make docker-build
make docker-run            # reads .env for LLM_API_KEY
```

Try it:

```bash
curl -s localhost:8080/healthz
curl -s localhost:8080/ask -H 'content-type: application/json' \
  -d '{"question": "How many minor versions may the kubelet lag behind kube-apiserver?", "top_k": 5}'
```

`version` is an optional extra field (`"1.27"` or `"1.31"`) that pins retrieval to
one release.

Other commands: `make search Q="..."` shows raw retrieval per release, `make ask
Q="..."` prints one full answer without starting the server, `make recall` runs
the retrieval-only ablation, `make smoke` runs the brief's validation scenarios
against a running server, and `make check` runs ruff, pylint, mypy and pytest.

Every setting is an environment variable (see `.env.example`). There are no keys
or absolute paths in the source.

## Corpus

From `https://github.com/kubernetes/website`, fetched on 2026-11-25 (UTC):

| Release | Branch | Commit | Pages |
|---|---|---|---|
| 1.27 | `release-1.27` | `f173f35615f0e87a49d963f28908cf25ebc538af` | 335 |
| 1.31 | `release-1.31` | `11f92a075a2a6b97448d8bb586ad7eac14871e04` | 357 |

Paths taken from each branch:
- `content/en/docs/concepts/`
- `content/en/docs/tasks/`
- `content/en/releases/version-skew-policy.md`

I included the version skew page because the kubelet skew really changed between
these releases. The brief's own example question is about it.

For 1.31 I also pulled `content/en/docs/reference/command-line-tools-reference/feature-gates/`,
as **metadata only**. Those files are never indexed as pages. In 1.31, many pages
write `{{< feature-state feature_gate_name="X" >}}` and the alpha/beta/stable stage
lives in that gate file. Without it, the maturity information, which is where most
real version differences live, would simply disappear from 1.31.

`scripts/fetch_corpus.sh` reproduces the corpus exactly, and `corpus/MANIFEST.json`
records the same details. After chunking: 2,881 chunks for 1.27 and 3,166 for 1.31
(about 20 pages per release are empty section indexes and produce no chunks).

## Architecture

```
POST /ask
  │
  ├─ input guard ─────── empty / non-English → refuse; >1000 chars → trimmed
  ├─ G2 false premise ── a --flag, FeatureGate or `identifier` that appears nowhere
  │                      in either release (exact term index) → refuse
  ├─ retrieve, per release on its own
  │     BM25 top 30 ┐
  │     dense top 30┴─ RRF ─ cross-encoder rerank ─ top k
  ├─ G1 weak retrieval ─ best rerank score < threshold → refuse
  ├─ context: top 3 per release + each chunk's counterpart in the other release
  ├─ LLM → JSON: sentences, each with chunk ids and quotes
  ├─ validator, per sentence:
  │     quote must be in the chunk · numbers and maturity words must be in the
  │     cited text · NLI must not contradict, and must entail or be closely covered
  ├─ G3 nothing survived → refuse
  └─ answer text and [chunk_id] markers assembled in code from what survived
```

The model never writes the final answer string. It proposes sentences with
citations; code checks them, drops what fails, and builds the answer. That's what
guarantees every marker has a citation entry and every quote is a real substring.

More detail: [docs/architecture.md](docs/architecture.md).

## Choices, and why

**Chunking.** Pages are split on their `##` and `###` headings, because that's how
these docs are organised: one heading, one idea. Long sections are split on
paragraph breaks (never through a code fence) to about 1,800 characters, and
one-line sections like "What's next" are merged into their neighbour. The bigger
decision was rendering Hugo shortcodes before chunking. `{{< skew currentVersion >}}`
renders differently per branch: left raw, the version skew page reads the same in
both releases. Rendered, 1.27 says kubelet can trail by "1.26 or 1.25" and 1.31 by
"1.30, 1.29, or 1.28". The same goes for `feature-state`. Full reasoning in
[docs/architecture.md](docs/architecture.md#chunking).

**Retrieval.** BM25 and dense (`bge-small-en-v1.5`) for each release separately,
fused with reciprocal rank fusion, then reranked with
`cross-encoder/ms-marco-MiniLM-L-6-v2`. Searching each release separately means one
release can't crowd the other out of the top k.

**Document identity across releases.** This turned out to matter more than
anything else in the pipeline. Pages are paired by `doc_id`, and two pages that
moved between releases are paired by title or word overlap (one was found; a
rewritten security page was deliberately left unpaired). The first eval run showed
that pairing *pages* wasn't enough: each release's top 3 was picked independently,
so the 1.27 and 1.31 versions of the same section often didn't both reach the model.
Now every chunk in the context brings its counterpart (same page, same section) from
the other release. That one change took version conflicts from 3/9 to 7/9.

**Refusal.** Three gates, each catching a different failure:
- **G2, false premise.** The question names a flag, gate or identifier that occurs
  nowhere in either release. It's checked against an exact term index of the whole
  corpus, not against retrieved chunks, because "not retrieved" and "doesn't exist"
  are different things.
- **G1, weak retrieval.** The best rerank score is below `REFUSAL_THRESHOLD=0.05`.
  This only catches clearly off-topic questions, and on purpose. On the dev set,
  near-topic unanswerable questions ("default --max-pods?") scored 0.92–0.94, close
  to answerable ones (0.996 and up). An off-topic question scored 0.006. A higher threshold
  would start refusing real questions, and no threshold separates the near-topic
  cases, so they're left to the next gate. The threshold came from the dev split
  only.
- **G3, nothing supported.** The model may say it can't answer, and every sentence
  it does write must survive the validator. If nothing survives, the response is a
  refusal that says what was missing.

## What counts as a hallucination

A response that is **not a refusal and is wrong**: it answers a question that should
have been refused, or it states something the docs don't support (in scoring terms,
it misses a fact the expected answer requires). A refusal is never counted as a
hallucination; it's counted as a false refusal instead, so both failure directions
stay visible.

## Results

Measured with `make eval` on an HP Pavilion 14 laptop (12th-gen Intel Core,
Alder Lake-U, 8 GB RAM, no GPU), Python 3.12, `openai/gpt-oss-120b` on Groq's free
tier at temperature 0. Full numbers per question are in `eval_report.json`, and the
per-question traces are in `eval/traces_*.jsonl`.

| | **Test** (36) | Dev (10) | Post-failure (10) |
|---|---|---|---|
| Accuracy | **75.0%** | 60.0% | 80.0% |
| Refusal rate on unanswerable + false premise | **100%** (11/11) | 100% (3/3) | 100% (3/3) |
| False-refusal rate | 24.0% | 42.9% | 28.6% |
| Hallucination rate | 8.3% | 10.0% | 0.0% |
| Version conflicts named and cited both | **7/9** | 2/2 | 4/6 |
| Citation validity (quote is exact substring) | **100%** | 100% | 100% |
| Retrieval recall@5 | **100%** | 100% | 100% |
| p95 latency | 17.3 s | 20.3 s | 15.2 s |

**Latency.** p95 includes waiting out Groq's free-tier rate limit (12K tokens per
minute). A single question without queueing takes about 2–5 s on this laptop;
retrieval plus reranking is about 1 s of that.

**Retrieval ablation** (`make recall`, test set, recall@5):

| Mode | recall@5 | both releases found (conflicts) | p95 retrieval |
|---|---|---|---|
| BM25 only | 0.96 | 1.0 | 8 ms |
| Dense only | 0.96 | 1.0 | 17 ms |
| Hybrid (RRF) | **1.00** | 1.0 | 27 ms |
| Hybrid + rerank (MiniLM-L6) | 1.00 | 1.0 | 1.2 s |
| Hybrid + rerank (bge-reranker-base, first try) | 1.00 | 1.0 | 18.8 s |

Hybrid bought four points over either retriever alone. The reranker bought no
recall on top of that. The first reranker I tried, `bge-reranker-base`, pushed p95
retrieval to 18.8 s on this CPU, so I swapped it for MiniLM-L6 at 1.2 s.
`eval/retrieval_ablation.json` also has recall@3, which is what the model actually sees. The reranker stays for two
reasons: it orders the top 3 that the model actually sees, and its score is the
signal behind G1. It doesn't earn its place on recall, and I'd rather say so.

### Before and after, stated plainly

I changed the pipeline after looking at the first test run. That's worth stating
directly, because it means the test set is no longer fully unseen.

| Test set | Run 1 | Run 2 |
|---|---|---|
| Accuracy | 63.9% | 75.0% |
| Version conflicts | 3/9 | 7/9 |
| False refusals | 28.0% | 24.0% |
| Hallucination | 16.7% | 8.3% |

What changed was design (counterpart context, title-aware support check, a maturity
guard, prompt rules for comparing releases), not thresholds fitted to labels. To
check that the fixes generalise, I wrote the post-failure slice *before* the second
run: six new version conflicts, two unanswerable questions, one false premise and
one version gap, none of which the system had seen. It scored 80%, which is
reassuring but not proof. Run 1 is kept in `eval/eval_report_v1_baseline.json`.

### The three most confidently wrong

1. **T-06, StatefulSet start ordinal** (retrieval score 1.0). It answered for 1.27
   (beta, needs the gate) but the 1.31 sentence was dropped by the support check, so
   the answer never mentions that 1.31 made it stable. A partial answer delivered
   with full confidence: the worst kind, because nothing in it is false.
2. **T-07, KMS v1** (1.0). The 1.31 sentence about deprecation had a quote the
   validator couldn't find verbatim, so it was dropped. What remained is true for
   1.27 but leaves out the single most important fact: KMS v1 is deprecated.
3. **T-36, pinning a Pod to a node** (1.0). The answer is right in substance (label
   the node, use `nodeSelector`), but it cites the DaemonSet page and doesn't say
   `kubectl label`, so it fails the keyword check. I've left the label alone
   rather than edit it after seeing the result.

### Where the remaining failures come from

Every wrong answer had its gold page retrieved (recall is 100%), so none are
retrieval misses. From the traces:

| Pattern | Questions | What happened |
|---|---|---|
| Quote not verbatim | T-23, T-30, D-06, P-04, part of T-07 | The model paraphrased inside its quote, so the validator refused to accept it |
| Support check too strict | T-26, T-33, D-08, D-09, P-05, part of T-06 | Correct sentences judged "neutral" by NLI and below the coverage bar |
| Context trimming | T-28 | The model saw the "Size limit" heading, but the 1 MiB value sat past the 1,000-character trim |
| Strict scoring | T-36, D-10 | Right in substance, fails the keyword check |

All four fail toward refusing rather than inventing, which is the direction I chose
to err in. Unanswerable questions were refused 100% of the time across all three
sets.

## Features

Core: everything in the brief, including schema-valid responses on every path
(broken JSON, an empty question, 4,000 characters, another language and an LLM
outage all return the normal schema, never a 500), deterministic ingestion
(rebuilding twice gives byte-identical files, and there's a test for it), and
configuration by environment only.

Bonus, implemented:
- Hybrid retrieval with an ablation (above)
- A reranker with before/after numbers, including the honest result that it added no recall
- A `version` filter on `/ask`
- A second eval slice written after seeing failures, reported separately
- Confidence buckets in `eval_report.json` (accuracy of answered questions grouped
  by retrieval score). With this few answered questions per bucket, it's an
  observation, not a calibration claim.

Not implemented: the citation UI. See below.

## Known issues

- **False refusals at 24%.** The validator is strict on purpose, and it costs
  correct answers. The obvious next steps are to let the model see full chunks
  rather than trimmed ones (fixes T-28) and to ask for shorter, single-clause quotes
  (fewer non-verbatim quotes).
- **Example manifests aren't ingested.** Task pages often say "apply this file" and
  the YAML lives in a separate example file. T-36 is a symptom.
- **Partial conflict answers.** When one release's sentence fails validation, the
  answer covers only the other release (T-06, T-07). A rule that refuses, or at
  least flags, a one-sided answer when both releases' versions of a section were in
  context would catch this.
- **Scoring is keyword-based.** It's deterministic and cheap, but stricter than a
  human reader. I'd rather report numbers a reviewer can reproduce exactly than add
  an LLM judge.
- **Free-tier limits.** Groq's daily token cap allows roughly one full eval run per
  day. `make eval` caches replies in `eval/.llm_cache/` (gitignored), so repeat runs
  and rebuild checks don't spend quota. Delete the folder for a cold run.
- **The 1.31 security overview** was rewritten rather than moved, and is not
  paired with its 1.27 ancestor.

## What I left out, and why

- **The citation UI.** The time went into the second eval round instead, which moved
  version conflicts from 3/9 to 7/9. That seemed a better use of the hours.
- **An LLM judge for answer quality.** Keyword scoring is reproducible to the digit,
  and the brief checks reproducibility.
- **A bigger reranker or GPU path.** No GPU on this machine, and the ablation showed
  the reranker buys no recall here.
- **More tuning after run 2.** Another round would have been tuning to my own test
  set, which the held-out questions would punish.
- **The rest of the docs site.** 335 and 357 pages is enough to have real
  disagreements, and a bounded, stated corpus was the brief's preference.

## Repository map

```
app/         FastAPI app, settings, response schema
rag/         chunker, ingest, retriever, refusal gates, LLM client,
             prompt/generator, validator, pipeline
eval/        question sets, eval and ablation scripts, traces, run-1 report
tests/       63 tests: chunking, determinism, retrieval, validator, gates,
             pipeline, API contract, scoring
docs/        architecture, evaluation method, decisions log
corpus/      the two releases as fetched, plus MANIFEST.json
benchmarks/  model load and inference timings on this machine
```

AI-assisted work is described in [AI_USAGE.md](AI_USAGE.md).
