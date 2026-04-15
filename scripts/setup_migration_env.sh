#!/usr/bin/env bash
# One-time local environment setup for run_migration.py.
#
# The generated Azure Functions import azure.* SDK packages; the tester
# subprocesses pytest which needs these installed in the current env. The
# reviewer also runs Bicep validation — install the Azure CLI and the
# bicep extension so Gate 8 actually passes.
set -euo pipefail

echo "[1/3] Installing Python Azure SDK packages..."
python3 -m pip install --upgrade \
  azure-functions \
  azure-identity \
  azure-cosmos \
  azure-servicebus \
  azure-storage-blob \
  azure-data-tables \
  azure-keyvault-secrets \
  azure-eventgrid \
  azure-monitor-opentelemetry

echo "[2/3] Checking for Azure CLI..."
if ! command -v az >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    echo "  Installing via Homebrew..."
    brew install azure-cli
  else
    echo "  WARNING: Homebrew not found. Install Azure CLI manually:"
    echo "  https://docs.microsoft.com/cli/azure/install-azure-cli"
  fi
else
  echo "  Azure CLI already installed: $(az --version | head -1)"
fi

echo "[3/3] Installing Bicep extension..."
if command -v az >/dev/null 2>&1; then
  az bicep install 2>&1 | tail -5 || az bicep upgrade 2>&1 | tail -5 || true
  echo "  Bicep version: $(az bicep version 2>&1 | head -1)"
fi

echo
echo "Setup complete. Now run: python3 run_migration.py"
