.RECIPEPREFIX = >
.PHONY: help setup fetch ingest search ask recall serve eval bench lint format typecheck test check docker-build docker-run clean

PY ?= python

help:
> @echo "setup        install dev dependencies"
> @echo "fetch        pull the two doc releases into corpus/"
> @echo "ingest       rebuild the index from corpus/ (wipes index/ first)"
> @echo "search       Q=\"question\"  show top retrieved chunks per version"
> @echo "ask          Q=\"question\"  full answer as JSON, no server needed"
> @echo "recall       retrieval-only recall@5 for every mode (ablation)"
> @echo "serve        run the API on PORT (default 8080)"
> @echo "eval         run the eval and write eval_report.json (LLM replies cached in eval/.llm_cache)"
> @echo "bench        check GPU, VRAM and model load times"
> @echo "check        format check, lint, typecheck and tests"

setup:
> $(PY) -m pip install -r requirements-dev.txt

fetch:
> bash scripts/fetch_corpus.sh

ingest:
> $(PY) -m rag.ingest

search:
> $(PY) -m rag.retriever $(Q)

ask:
> $(PY) -m rag.pipeline $(Q)

recall:
> $(PY) -m eval.retrieval_eval

serve:
> uvicorn app.main:app --host 0.0.0.0 --port $${PORT:-8080}

eval:
> LLM_CACHE_DIR=$${LLM_CACHE_DIR:-eval/.llm_cache} $(PY) -m eval.run_eval

bench:
> $(PY) benchmarks/bench_gpu.py

lint:
> ruff check .
> pylint app rag eval

format:
> ruff format .
> ruff check --fix .

typecheck:
> mypy app rag eval

test:
> pytest

check:
> ruff format --check .
> ruff check .
> pylint app rag eval
> mypy app rag eval
> pytest

docker-build:
> docker build -t aion-docs-assistant .

docker-run:
> docker run --rm -p 8080:8080 --env-file .env aion-docs-assistant

clean:
> rm -rf index/* .pytest_cache .mypy_cache .ruff_cache
> touch index/.gitkeep
