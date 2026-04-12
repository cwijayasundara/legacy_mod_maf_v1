# MS Agent Harness — Pure Python container
#
# Build:  docker build -t ms-agent-harness .
# Run:    docker run -p 8000:8000 -e OPENAI_API_KEY=sk-... ms-agent-harness

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/ms-agent-harness

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY . .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "agent_harness.orchestrator.api:app", "--host", "0.0.0.0", "--port", "8000"]
