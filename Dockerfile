# CPU image so it runs on any reviewer machine. The models are small enough for that.
# Python 3.12 matches the version the numbers in the README were measured on.
FROM python:3.12-slim

WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080 DEVICE=cpu

RUN pip install --no-cache-dir torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app app
COPY rag rag
COPY eval eval
COPY corpus corpus

# Build the index inside the image so the container starts ready.
RUN python -m rag.ingest
# Pre-download the reranker so the container starts without fetching it. (The NLI model is
# off by default and is only fetched at startup if NLI_ENABLED=true.) Plain HTTP downloads
# with retries; if it still fails, the build continues and the model loads at startup.
RUN for i in 1 2 3; do HF_HUB_DISABLE_XET=1 python -c "from rag.models import get_reranker; get_reranker()" && break || sleep 15; done || true

EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
