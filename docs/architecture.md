# Architecture

The full request flow gets written up once Part 2 is built. This page starts with
ingestion, because everything downstream depends on it.

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
