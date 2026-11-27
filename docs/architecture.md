# Architecture

## A request, step by step

1. **Input guard.** The question is coerced to text, whitespace is collapsed and it
   is cut to 1,000 characters. Empty questions are refused. A question is treated
   as non-English when fewer than half its words are English stopwords or words that
   occur in the corpus.
2. **G2, false premise.** Flags (`--x`), CamelCase identifiers and backticked tokens
   in the question are looked up in `index/term_index.json`, which lists every such
   term in both releases. Any miss means a refusal that names the term.
3. **Retrieval.** For each release separately: BM25 top 30 and dense top 30, merged
   with reciprocal rank fusion (k = 60), the top 10 reranked by a cross-encoder,
   top k kept. Pages are grouped across releases by `doc_id` (with aliases for moved pages).
4. **G1, weak retrieval.** If the best rerank score is under the threshold, refuse.
5. **Context.** The top 3 chunks per release, plus each one's counterpart in the
   other release: same page and same heading path, or the most similar chunk of
   that page. Chunks are trimmed to 1,000 characters for the prompt only; quotes
   are always checked against the full chunk.
6. **Generation.** The model returns JSON: sentences, each with chunk ids and
   quotes; optional "gaps" (a release doesn't cover the topic); or "not answerable"
   with what's missing.
7. **Validation.** Described below. Sentences that fail are dropped, never repaired.
8. **G3.** No surviving sentence means a refusal, carrying the model's explanation
   of what is missing.
9. **Assembly.** Code writes the answer from the surviving sentences, adds the
   `[chunk_id]` markers and builds `citations` from the same objects. Gaps are kept
   only if they are a plain "release X doesn't cover this" statement.

Every path, including exceptions and an unreachable LLM, returns the same
response schema.

## The validator

For each proposed sentence:

- **Citation check.** The chunk id must be one that was in context, and the quote
  must occur in that chunk. Matching first ignores whitespace, curly quotes and
  markdown backticks or asterisks. If that fails, a near-verbatim quote (a dropped
  word, two lines joined) is aligned to the closest real span, but only when it is at
  least 90% similar and states the same numbers and maturity words. Either way, the
  quote that's returned is cut from the chunk's own text, so it's always an exact
  substring.
- **Numbers and maturity.** Every number and every maturity word (alpha, beta,
  stable, deprecated, GA) in the sentence must appear in the cited text. These are
  exactly what differs between releases.
- **No NLI model.** An NLI support check was tried and removed: the ablation showed it
  refused correct answers without stopping any wrong ones (see
  [evaluation.md](evaluation.md)).

After validation, if the surviving sentences cite only one release, the pipeline
looks at the other release's twin of each cited section. If that twin states a
different `FEATURE STATE`, the line is added as its own sentence, quoted verbatim
and cited. Nothing in that step is generated.

Each decision is recorded in the eval traces with its scores and reason.

## Ingestion

`make ingest` reads `corpus/`, wipes `index/` and writes it again. Pages are read
in sorted order and nothing time-based is written, so two runs on the same corpus
produce byte-identical files. There's a test for exactly that.

## Chunking

The Kubernetes docs are Hugo pages, and that shapes every choice here.

Each page is split on its `##` and `###` headings, because that is how the docs
are organised: one heading, one idea, such as "kubelet" under the version skew
policy or "Pod phase" under the pod lifecycle. Sections over about 1,800 characters
(roughly 400 tokens) are split on paragraph breaks, never through a code fence.
Sections under 300 characters get merged with the next one, because many "What's
next" and "Before you begin" sections are a single line and carry nothing on their
own. Each chunk is embedded with its page title and heading path in front, so a
chunk that just says "Optionally upgrade kubelet instances..." still knows it
belongs to the version skew policy.

Before splitting, Hugo shortcodes are rendered to the text a reader would see.
This matters more than it looks:

- `{{< skew currentVersion >}}` and its relatives render differently per branch.
  Left raw, the version skew page reads the same in 1.27 and 1.31. Rendered, one
  says kubelet can lag "1.26 or 1.25" and the other "1.30, 1.29, or 1.28".
- `{{< feature-state >}}` carries alpha/beta/stable maturity, which is where a lot
  of real version differences live. In 1.31 many pages only name the feature gate
  and the stage lives in a separate metadata file, so those files are fetched too
  (as metadata, not as pages) and the stage is worked out for the right release.
- Notes, tabs and glossary tooltips keep their text; includes, comments and
  mermaid diagrams are dropped.

Chunk ids look like `v1.31:releases/version-skew-policy#c9`: version, page path,
position. They only change if the page itself changes.

## Pages that moved between releases

Pairing 1.27 and 1.31 by `doc_id` breaks when a page was moved or renamed. For
pages that exist in only one release, ingestion tries to find the twin: first by
identical title, then by word overlap. A content match needs a Jaccard score of at
least 0.5 and must be at least twice the runner-up. On this corpus that pairs
"Managing Resources" (1.27) with "Managing Workloads" (1.31) at 0.73. The security
overview was rewritten rather than moved, scores too close to call, and is
deliberately left unpaired. A wrong pairing would be worse than none.
