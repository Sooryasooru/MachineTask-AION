# Decisions and trade-offs

Written as I went, not tidied up afterwards.

| Decision | Why | What it costs |
|---|---|---|
| CPU only | The laptop has Intel Iris Xe, no CUDA. The models are small enough. | Ingest takes about 10 minutes |
| `bge-small-en-v1.5` embeddings | Small, good, and named in the brief | |
| FAISS flat index on disk | No server, exact search, identical results on every rebuild | Wouldn't scale to millions of chunks, which isn't needed here |
| BM25 + dense with RRF | The ablation showed 0.96 → 1.00 recall@5 | Two indexes to keep in step |
| Each release searched on its own | One release can't push the other out of the top k | Twice the retrieval work |
| MiniLM-L6 reranker instead of `bge-reranker-base` | bge-base gave p95 retrieval of 18.8 s on this CPU and no recall gain | Somewhat weaker ordering |
| Counterpart chunks from the other release | Run 1 showed conflicts lost because one release's section didn't make its top 3 | Larger prompts |
| Model returns JSON, code writes the answer | Markers and citations can't drift apart | One more parsing step |
| No quote repair | A quote that isn't in the chunk is evidence the sentence isn't grounded. Fixing the quote would hide that. | More false refusals |
| Numbers and maturity words must appear in cited text | NLI models are weak on numbers, and "two" vs "three" is exactly the error that matters here | Can drop a sentence that rephrases a number |
| Term index for false premises | "Not retrieved" isn't "doesn't exist". An exact lookup over both releases is cheap and certain. | Unusual CamelCase words outside the docs get refused |
| Language check by vocabulary, not a detector | Short technical questions confuse language detectors; corpus vocabulary doesn't | Very short non-English questions full of English terms pass |
| Generic OpenAI-compatible client | Groq retired the first model I planned on mid-build, and switching provider is one env var | |
| `gpt-oss-120b` with low reasoning effort | Largest model on the free tier, follows the JSON rules well | Daily token cap; responses cached during eval |
| Keyword scoring | Reproducible to the digit | Stricter than a human (T-36) |

## Left out on purpose

- Citation UI: time went into the second eval round instead
- LLM-as-judge: keyword scoring is reproducible
- Tuning after run 2: would have been fitting my own test labels
- Example YAML files and the rest of the docs site: bounded corpus by design
