# Evaluation method

## Question sets

| File | Size | Role |
|---|---|---|
| `eval/questions_holdout.jsonl` | 20 | Headline numbers from now on. Written and frozen (commit `3e8ada7`) before any of the week-two changes. Drafted with AI from the docs, each answer checked by me against the source line. |
| `eval/questions_holdout2.jsonl` | 13 | Written and frozen after the first holdout run, before the follow-up fix that came from reading holdout answers. Same drafting and checking as the holdout. |
| `eval/questions_test.jsonl` | 36 | Written before the first run. Seen during development (runs 1 to 3), so no longer unseen. |
| `eval/questions_dev.jsonl` | 20 | Practice set for tuning: the original 10 dev questions plus the 10 written after run 1 (P-01 to P-10). |

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

## Runs

| Test set | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| Accuracy | 63.9% | 75.0% | 86.1% |
| Version conflicts | 3/9 | 7/9 | 8/9 |
| Wrongly refused | 28% | 24% | 8% |
| Unanswerable refused | 11/11 | 11/11 | 11/11 |

Run 3 replays run 2's recorded model replies exactly (0 live calls); only the
checking after the model changed. Its changes came from an outside review of run 2
and from the traces, after seeing failures on all three sets, so none of them is
unseen any more.

## NLI ablation (the check has since been removed)

Same recorded replies, NLI support check on and off. Dev and post-failure were still
separate sets at the time:

| | Test on | Test off | Dev on | Dev off | Post-failure on | Post-failure off |
|---|---|---|---|---|---|---|
| Accuracy | 77.8% | 86.1% | 60% | 80% | 90% | 100% |
| Wrongly refused | 24% | 8% | 43% | 14% | 14% | 0% |
| Answered but incomplete | 2 | 3 | 1 | 1 | 0 | 0 |
| Answered what should be refused | 0 | 0 | 0 | 0 | 0 | 0 |

The rule set before measuring was to keep NLI only if it stopped wrong answers.
Without it, one extra answer counted as incomplete (T-35). On reading it, that
answer is correct and fully quoted but leaves out the flag name the scoring
requires. NLI was switched off on that basis, and in week two the code and model were
removed entirely. The NLI-on report is kept as evidence:
`eval/eval_report_run3_nli_on.json`.

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
