# AION take-home: grounded documentation assistant

A question-answering service over two releases of the Kubernetes docs (1.27 and
1.31). It cites the exact text it relies on, says so when the docs don't cover
something, and names both versions when they disagree.

> Work in progress. Sections marked TBD get filled in as the build goes.

## Running it from a clean machine

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install torch --index-url https://download.pytorch.org/whl/cu121   # or /cpu
make setup
cp .env.example .env               # add your GROQ_API_KEY
make fetch                         # pull the corpus
make ingest                        # build the index
make serve                         # http://localhost:8080
make eval                          # writes eval_report.json
```

With Docker:

```bash
make docker-build
make docker-run
```

## Corpus

TBD: exact paths, branches and the date I pulled them.

## How it works

See [docs/architecture.md](docs/architecture.md). Short version: retrieve from each
version separately, pair pages by `doc_id`, rerank, generate with the context
grouped by version, then check every sentence against the chunk it cites and drop
anything that doesn't hold up.

## What counts as a hallucination here

A factual sentence that the chunk it cites doesn't support, or any answer at all
to a question that should have been refused.

## Results

TBD: accuracy, refusal rate, false-refusal rate, citation validity, recall@5,
p95 latency, the hardware they came from, and the command that reproduces them.

## What I left out

TBD. See [docs/decisions.md](docs/decisions.md).

## Development

```bash
make format     # ruff format + autofix
make check      # format check, ruff, pylint, mypy, pytest
```

Code style is PEP 8, enforced by ruff and pylint, with type hints checked by mypy.
