# Decisions and trade-offs

Written as I went, not tidied up afterwards.

| Decision | Why | What it costs |
|---|---|---|
| CPU only | The laptop has Intel Iris Xe, no CUDA. The models are small enough. | Ingest takes about 10 minutes |
| `bge-small-en-v1.5` embeddings | Small, good, and named in the brief | |
| FAISS flat index on disk | No server, exact search, identical results on every rebuild | Wouldn't scale to millions of chunks, which isn't needed here |
| Keep the reranker even though recall@3 and @5 are equal without it | Its top score is the G1 "is this answerable at all?" signal | About 1 s of CPU per question |
| BM25 + dense with RRF | The ablation showed 0.96 → 1.00 recall@5 | Two indexes to keep in step |
| Each release searched on its own | One release can't push the other out of the top k | Twice the retrieval work |
| MiniLM-L6 reranker instead of `bge-reranker-base` | bge-base gave p95 retrieval of 18.8 s on this CPU and no recall gain | Somewhat weaker ordering |
| Counterpart chunks from the other release | Run 1 showed conflicts lost because one release's section didn't make its top 3 | Larger prompts |
| Model returns JSON, code writes the answer | Markers and citations can't drift apart | One more parsing step |
| NLI support check removed (off in run 3, deleted in week two) | The ablation showed it refused correct answers and stopped no wrong ones | Relies on the quote, number and stage checks alone |
| Code adds the other release's feature state | Run 2 left one-sided version answers (T-06, T-07) when one sentence failed its check | Only works when the twin section states a different feature state |
| False-premise check: flags, backticks, and CamelCase only for feature gates | CamelCase alone would refuse product names like PostgreSQL | An invented gate named without the word "gate" goes to the model instead |
| Pinned dependency versions | The numbers should reproduce with the same libraries | Upgrades need a deliberate bump |
| Align near-verbatim quotes, never repair content (changed in run 3) | At first no quote was ever adjusted. Run 2's traces showed correct sentences dropped over a missing word, so near-verbatim quotes (90%+ similar, same numbers and stages) now snap to the real span. The returned quote is still the chunk's own text. | A small risk of aligning a loose paraphrase; the number and stage guard limits it |
| Say when a cited feature is alpha, beta or deprecated (week two, after the holdout run) | Holdout answers H-07 to H-09 explained a feature correctly but never said it was alpha or beta, the first thing a user needs before relying on it. Added only when the cited section has exactly one FEATURE STATE line, quoted verbatim. Came from reading holdout answers, so the 80% holdout figure is from before it; holdout2 was frozen first to measure it honestly. | One more sentence on some answers |
| One retry, merged in, never swapped in (week two) | Test/dev traces showed right answers lost to trimmed excerpts (T-28) or a quote copied loosely (T-07, D-06). The retry shows excerpts untrimmed and lists the quotes that failed. | One extra model call on those questions only; everything already kept stays |
| Spliced quotes keep their longest verbatim piece (week two) | The model sometimes joins two passages with "..." or swaps two sentences; each piece is still real text | The citation shows only part of what the model quoted |
| /ask time limit (`REQUEST_TIMEOUT_S`, 30 s) | A rate-limited model call should not hold a request open; the caller gets a schema-valid refusal | A slow but correct answer can be cut off |
| Numbers and maturity words must appear in cited text | NLI models are weak on numbers, and "two" vs "three" is exactly the error that matters here | Can drop a sentence that rephrases a number |
| Term index for false premises | "Not retrieved" isn't "doesn't exist". An exact lookup over both releases is cheap and certain. | Unusual CamelCase words outside the docs get refused |
| Language check by vocabulary, not a detector | Short technical questions confuse language detectors; corpus vocabulary doesn't | Very short non-English questions full of English terms pass |
| Generic OpenAI-compatible client | Groq retired the first model I planned on mid-build, and switching provider is one env var | |
| `gpt-oss-120b` with low reasoning effort | Largest model on the free tier, follows the JSON rules well | Daily token cap; responses cached during eval |
| Keyword scoring | Reproducible to the digit | Stricter than a human (T-36) |

## Left out on purpose

- A UI framework: the page is one static HTML file, served by the API
- LLM-as-judge: keyword scoring is reproducible
- Tuning after run 2: would have been fitting my own test labels
- Example YAML files and the rest of the docs site: bounded corpus by design
