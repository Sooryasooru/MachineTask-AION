# Evaluation method

## Three question sets

| File | Size | Role |
|---|---|---|
| `eval/questions_test.jsonl` | 36 | Headline numbers. Written before the first run. |
| `eval/questions_dev.jsonl` | 10 | The only set thresholds were looked at against (G1). |
| `eval/questions_postfail.jsonl` | 10 | Written after run 1, before run 2. Reported on its own. |

Test set by type: 9 version conflicts, 8 unanswerable, 3 false premise, 4 version
gaps (only one release documents it), 8 factual, 4 procedural.

### How the questions were found

Version conflicts came from comparing the rendered `FEATURE STATE` lines of every
section present in both releases. That listed 25 sections whose maturity changed.
I then read the pairs side by side, kept the clearest ones and wrote the questions.
Two finds I didn't expect:

- **Evented PLEG went backwards**: the 1.27 page says beta, the 1.31 gate metadata
  says alpha. A system that assumes features only mature would get this wrong.
- **`node-monitor-grace-period`** (40 seconds) is documented in 1.27 and gone from
  1.31: a version gap in the reverse direction.

Unanswerable questions are deliberately close to the corpus: node limits, etcd
sizing, SLA, CoreDNS defaults. Each one was checked with a search over both
releases to make sure the answer really isn't there. Questions that are obviously
off-topic would test nothing. False-premise flags and gates were checked against
the term index to make sure they don't exist.

Every `must_include` term was checked to appear in its gold pages before the first
run. One question (T-36) was corrected at that stage, because its `nodeSelector`
YAML lives in an example file that isn't ingested. After the first run no test label
was changed.

## Scoring

Deterministic, no LLM judge:

- **Should refuse** (unanswerable, false premise): correct when `refused` is true
  and `citations` is empty.
- **Should answer**: correct when not refused and every `must_include` string
  appears in the answer text. `[chunk_id]` markers are stripped first, so the
  "1.27" inside an id doesn't count as naming the release.
- **Version conflicts** also need both releases named in the text and at least
  one citation from each.

## Metrics

| Metric | Definition |
|---|---|
| accuracy | correct / all questions |
| refusal rate | refused / questions that should be refused |
| false-refusal rate | refused / questions that should be answered |
| hallucination rate | not refused and not correct / all questions |
| citation validity | citations whose quote is an exact substring of the indexed chunk / all citations, checked against `index/chunks.jsonl` independently of the pipeline |
| marker integrity | answers whose `[markers]` exactly match their `citations` |
| recall@5 | answerable questions with a gold page in the top 5 of either release, from a retrieval call made separately from answering |
| attribution | each wrong answerable question is put down to retrieval (gold page not retrieved) or to generation and the gates (gold page retrieved) |
| p95 latency | nearest-rank 95th percentile of `latency_ms` |

## Refusal threshold

G1 compares the best rerank score with `REFUSAL_THRESHOLD`. On the dev set, with
the MiniLM reranker, answerable questions scored 0.996 and above, two near-topic
unanswerable questions scored 0.922 and 0.937, and an off-topic one scored 0.006.
The earlier bge reranker showed the same pattern (0.977+, 0.877/0.893, 0.001). A threshold cannot
separate the near-topic cases without refusing real questions, so G1 is set low
(0.05) and only stops clearly unrelated questions. Near-topic unanswerables are
handled by the model's own judgement and the validator, which is where they were
caught (8/8 on test).

## Reproducing

```bash
make ingest   # rebuild index from corpus/
make recall   # retrieval ablation -> eval/retrieval_ablation.json
make eval     # full run -> eval_report.json, eval/traces_*.jsonl
```

LLM replies are cached in `eval/.llm_cache/`, keyed on the exact request. Because
retrieval is deterministic, a rebuilt index produces the same prompts and the same
cached replies, so numbers reproduce exactly. Delete the cache for a cold run;
`gpt-oss-120b` at temperature 0 is close to, but not perfectly, deterministic.
