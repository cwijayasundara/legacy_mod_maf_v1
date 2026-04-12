#!/usr/bin/env node
// detect-secrets.js — Block writes containing API keys, tokens, or credentials
"use strict";

const fs = require("node:fs");
const { execFileSync } = require("node:child_process");

const filePath = process.argv[2] || "";

if (!filePath || !fs.existsSync(filePath)) {
  process.exit(0);
}

// Skip binary files
try {
  const fileType = execFileSync("file", [filePath], {
    encoding: "utf8",
  });
  if (/binary|executable/.test(fileType)) {
    process.exit(0);
  }
} catch {
  // If `file` command fails, continue checking
}

// Patterns that indicate hardcoded secrets
const PATTERNS = [
  /AKIA[0-9A-Z]{16}/, // AWS access key
  /sk-[a-zA-Z0-9]{48}/, // OpenAI API key
  /ghp_[a-zA-Z0-9]{36}/, // GitHub PAT
  /password\s*[:=]\s*["'][^\s"']{8,}/, // Hardcoded password
  /DefaultEndpointsProtocol=https;AccountName=/, // Azure connection string
  /AccountKey=[A-Za-z0-9+/=]{44,}/, // Azure storage key
  /Bearer\s+[A-Za-z0-9._~+/=-]{20,}/, // Bearer token
];

let content;
try {
  content = fs.readFileSync(filePath, "utf8");
} catch {
  process.exit(0);
}

for (const pattern of PATTERNS) {
  if (pattern.test(content)) {
    console.log(`[hook:secrets] BLOCKED: Possible secret detected in ${filePath}`);
    console.log(
      "Fix: Use environment variables, Azure Key Vault, or local.settings.json (gitignored)."
    );
    process.exit(1);
  }
}

process.exit(0);
