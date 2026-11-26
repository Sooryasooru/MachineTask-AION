"""Runs the brief's validation scenarios against a running service.

Start the API first (`make serve`), then: `make smoke`.
Checks that every response has exactly the required fields, and prints what came back.
"""

from __future__ import annotations

import json
import os
import sys

import httpx

BASE = f"http://localhost:{os.environ.get('PORT', '8080')}"
FIELDS = {"answer", "refused", "citations", "retrieved_chunk_ids", "latency_ms"}

CASES: list[tuple[str, object]] = [
    (
        "version conflict",
        {"question": "How many minor versions may the kubelet lag behind kube-apiserver?"},
    ),
    (
        "pinned to 1.27",
        {
            "question": "How many minor versions may the kubelet lag behind kube-apiserver?",
            "version": "1.27",
        },
    ),
    ("unanswerable", {"question": "What uptime SLA does the Kubernetes API server guarantee?"}),
    ("false premise", {"question": "What does the kubelet --max-pod-lag flag do?"}),
    ("empty string", {"question": ""}),
    ("4,000 characters", {"question": "kubelet " * 500}),
    ("other language", {"question": "¿Cuántas versiones menores puede retrasarse el kubelet?"}),
    ("wrong types", {"question": 42, "top_k": "five"}),
    ("not JSON", "this is not json"),
]


def main() -> int:
    """Print one line per scenario; exit non-zero if any response breaks the schema."""
    health = httpx.get(f"{BASE}/healthz", timeout=10)
    print(f"healthz            {health.status_code} {health.json()}")
    ready = httpx.get(f"{BASE}/readyz", timeout=10)
    print(f"readyz             {ready.status_code} {ready.json()}")
    failures = 0
    for name, body in CASES:
        if isinstance(body, str):
            resp = httpx.post(
                f"{BASE}/ask",
                content=body,
                timeout=120,
                headers={"content-type": "application/json"},
            )
        else:
            resp = httpx.post(f"{BASE}/ask", json=body, timeout=120)
        data = resp.json()
        ok = resp.status_code == 200 and set(data) == FIELDS
        if data.get("refused") and data.get("citations"):
            ok = False
        failures += not ok
        versions = sorted({c["version"] for c in data.get("citations", [])})
        print(
            f"{name:<18} {resp.status_code} {'ok ' if ok else 'BAD'} refused={data.get('refused')} "
            f"cited={versions} | {data.get('answer', '')[:90]}"
        )
    print(json.dumps({"schema_failures": failures}))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
