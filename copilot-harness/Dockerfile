# Copilot Harness — Container Image
#
# Build:  docker build -t copilot-harness .
# Run:    docker run -p 8000:8000 -e OPENAI_API_KEY=sk-... -e COPILOT_OFFLINE=true copilot-harness

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git gnupg \
    && rm -rf /var/lib/apt/lists/*

# Node.js 20 (required for Copilot CLI and hooks)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Copilot CLI
RUN npm install -g @githubnext/copilot-cli || echo "Copilot CLI install pending — check npm package name"

WORKDIR /app/copilot-harness

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY . .
RUN chmod +x .copilot/hooks/*.js 2>/dev/null || true

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "harness.orchestrator.api:app", "--host", "0.0.0.0", "--port", "8000"]
