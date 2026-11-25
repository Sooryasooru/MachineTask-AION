# Decisions and trade-offs

A running log, written as I go rather than tidied up at the end.

| Decision | Why | What it costs |
|---|---|---|
| Groq for generation, Ollama `qwen2.5:3b` as fallback | Laptop has about 7.4 GB RAM; a 70B model over a free API follows citation rules far better than anything that fits locally | Needs a free API key; the fallback is weaker |
| FAISS flat index on disk | No server to run, exact search, same results every rebuild | Wouldn't scale to millions of chunks, which this corpus doesn't need |

## Left out on purpose

TBD
