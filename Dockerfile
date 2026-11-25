# CPU image so it runs on any reviewer machine. The models are small enough for that.
FROM python:3.11-slim

WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080 DEVICE=cpu

RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app app
COPY rag rag
COPY eval eval
COPY corpus corpus

# Build the index inside the image so the container starts ready.
RUN python -m rag.ingest
# Download the reranker and NLI models too, so the container starts without fetching them.
RUN python -c "from rag.models import get_reranker, get_nli; get_reranker(); get_nli()"

EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
