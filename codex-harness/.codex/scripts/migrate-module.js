#!/usr/bin/env node
// migrate-module.js — Local CLI wrapper to run the full migration pipeline
// for a single Lambda module using Codex CLI.
//
// Usage:
//   ./.codex/scripts/migrate-module.js <module-name> <language> [work-item-id]
//
// Examples:
//   ./.codex/scripts/migrate-module.js order-processor python WI-1234
//   ./.codex/scripts/migrate-module.js payment-handler java
//   ./.codex/scripts/migrate-module.js user-api node WI-5678
//
// Prerequisites:
//   - Codex CLI installed: npm install -g @openai/codex
//   - OPENAI_API_KEY set in environment
//   - Azure Functions Core Tools (for local testing): npm install -g azure-functions-core-tools@4

"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

// --- Args ---
const args = process.argv.slice(2);
if (args.length < 2) {
  console.error(
    "Usage: migrate-module.js <module-name> <language> [work-item-id]"
  );
  process.exit(1);
}

const MODULE = args[0];
const LANGUAGE = args[1];
const WI_ID = args[2] || "LOCAL";

const SCRIPT_DIR = __dirname;
const PROJECT_ROOT = path.resolve(SCRIPT_DIR, "..", "..");

// --- Validation ---
try {
  execFileSync("which", ["codex"]);
} catch {
  console.error(
    "ERROR: Codex CLI not found. Install with: npm install -g @openai/codex"
  );
  process.exit(1);
}

// Load .env if present (from project root or parent)
for (const envFile of [
  path.join(PROJECT_ROOT, ".env"),
  path.join(PROJECT_ROOT, "..", ".env"),
]) {
  if (fs.existsSync(envFile)) {
    const lines = fs.readFileSync(envFile, "utf8").split("\n");
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      const eqIdx = trimmed.indexOf("=");
      if (eqIdx > 0) {
        const key = trimmed.substring(0, eqIdx).trim();
        let val = trimmed.substring(eqIdx + 1).trim();
        // Remove surrounding quotes
        if (
          (val.startsWith('"') && val.endsWith('"')) ||
          (val.startsWith("'") && val.endsWith("'"))
        ) {
          val = val.slice(1, -1);
        }
        if (!process.env[key]) {
          process.env[key] = val;
        }
      }
    }
    break;
  }
}

// Check for API key OR Codex ChatGPT auth
if (!process.env.OPENAI_API_KEY) {
  const authJson = path.join(
    process.env.HOME || process.env.USERPROFILE || "",
    ".codex",
    "auth.json"
  );
  let hasChatGPTAuth = false;
  try {
    const authContent = fs.readFileSync(authJson, "utf8");
    if (authContent.includes('"auth_mode": "chatgpt"')) {
      hasChatGPTAuth = true;
    }
  } catch {
    // no auth file
  }
  if (hasChatGPTAuth) {
    console.log("Using Codex ChatGPT authentication (no API key needed)");
  } else {
    console.error(
      "ERROR: OPENAI_API_KEY not set. Export it or add to .env file."
    );
    console.error("Alternatively, run: codex --login");
    process.exit(1);
  }
}

const VALID_LANGUAGES = ["java", "python", "node", "csharp"];
if (!VALID_LANGUAGES.includes(LANGUAGE)) {
  console.error(
    `ERROR: Invalid language '${LANGUAGE}'. Must be one of: ${VALID_LANGUAGES.join(", ")}`
  );
  process.exit(1);
}

// Check that source module exists
const SOURCE_DIR = path.join(PROJECT_ROOT, "src", "lambda", MODULE);
if (!fs.existsSync(SOURCE_DIR)) {
  console.error(`ERROR: Lambda source not found at ${SOURCE_DIR}`);
  console.error("Place your Lambda module source code there first.");
  process.exit(1);
}

// --- Prepare output directories ---
for (const dir of [
  path.join(PROJECT_ROOT, "migration-analysis", MODULE),
  path.join(PROJECT_ROOT, "src", "azure-functions", MODULE),
  path.join(PROJECT_ROOT, "infrastructure", MODULE),
  path.join(PROJECT_ROOT, "tests", MODULE),
]) {
  fs.mkdirSync(dir, { recursive: true });
}

// --- Compose the Codex task prompt ---
const PROMPT = `Migrate the AWS Lambda module '${MODULE}' (${LANGUAGE}) to Azure Functions.

Work Item: ${WI_ID}
Source: src/lambda/${MODULE}/
Target: src/azure-functions/${MODULE}/

BEFORE starting, read these context files:
- program.md — human steering constraints
- state/learned-rules.md — inject ALL rules (prevents repeated mistakes)
- state/migration-progress.txt — context from prior migrations
- state/coverage-baseline.txt — coverage floor (must meet or exceed)

Follow the AGENTS.md workflow strictly:

Step 0: Sprint Contract Negotiation
  -> Coder proposes sprint-contract.json, Tester finalizes (2-call handshake)
  -> Schema: templates/sprint-contract.json

Step 1: Run migration-analyzer on src/lambda/${MODULE}/
  -> Output: migration-analysis/${MODULE}/analysis.md

Step 2: Run migration-coder (TDD-first, ratcheting enabled)
  -> Propose sprint contract first
  -> Write tests, then migrate code, then generate Bicep template
  -> Output: src/azure-functions/${MODULE}/ + infrastructure/${MODULE}/main.bicep

Step 3: Run migration-tester (three-layer evaluation)
  -> Finalize sprint contract, then evaluate
  -> On failure: write structured eval-failures.json (not free-form text)
  -> Output: migration-analysis/${MODULE}/test-results.md

Step 4: Run migration-reviewer (8-point quality gate + contract validation)
  -> Output: migration-analysis/${MODULE}/review.md
  -> Update state/migration-progress.txt with session block

If reviewer APPROVEs:
  -> Create git branch: migrate/${WI_ID}-${MODULE}
  -> Commit: [${WI_ID}] Migrate ${MODULE} (${LANGUAGE}) to Azure Functions

If blocked after 3 self-healing attempts:
  -> Write migration-analysis/${MODULE}/blocked.md with root cause
  -> Append to state/failures.md
  -> Check for repeated errors -> add to state/learned-rules.md if pattern found
  -> Do NOT commit broken code`;

// --- Run Codex ---
console.log(
  "+==================================================================="
);
console.log(
  `|  Migration Agent Pipeline -- ${MODULE} (${LANGUAGE})`
);
console.log(`|  Work Item: ${WI_ID}`);
console.log(
  "|  Mode: Full auto (analyzer -> coder -> tester -> reviewer)"
);
console.log(
  "+==================================================================="
);
console.log("");
console.log("Starting Codex with full-auto approval mode...");
console.log("");

const logFile = path.join(
  PROJECT_ROOT,
  "migration-analysis",
  MODULE,
  "codex-output.log"
);

let exitCode = 0;
try {
  const output = execFileSync("codex", ["exec", "--full-auto", PROMPT], {
    encoding: "utf8",
    cwd: PROJECT_ROOT,
    stdio: ["inherit", "pipe", "pipe"],
    maxBuffer: 50 * 1024 * 1024,
  });
  process.stdout.write(output);
  fs.writeFileSync(logFile, output, "utf8");
} catch (err) {
  exitCode = err.status || 1;
  const output = (err.stdout || "") + (err.stderr || "");
  if (output) {
    process.stdout.write(output);
  }
  fs.writeFileSync(logFile, output, "utf8");
}

// --- Post-run summary ---
console.log("");
console.log("===================================================================");

if (exitCode === 0) {
  console.log(`Migration pipeline completed for ${MODULE}.`);
  console.log("");
  console.log("Outputs:");
  const checks = [
    [
      `migration-analysis/${MODULE}/analysis.md`,
      "Analysis",
    ],
    [
      `migration-analysis/${MODULE}/test-results.md`,
      "Test Results",
    ],
    [
      `migration-analysis/${MODULE}/review.md`,
      "Review",
    ],
  ];
  for (const [rel, label] of checks) {
    if (fs.existsSync(path.join(PROJECT_ROOT, rel))) {
      console.log(`  [ok] ${label.padEnd(14)} ${rel}`);
    }
  }
  const blockedPath = `migration-analysis/${MODULE}/blocked.md`;
  if (fs.existsSync(path.join(PROJECT_ROOT, blockedPath))) {
    console.log(`  [!!] BLOCKED        ${blockedPath}`);
  }
  console.log("");
  console.log(`Azure Function: src/azure-functions/${MODULE}/`);
  console.log(`Codex log:      migration-analysis/${MODULE}/codex-output.log`);
} else {
  console.error(`ERROR: Codex exited with code ${exitCode}`);
  console.error(`Check log: migration-analysis/${MODULE}/codex-output.log`);
}

process.exit(exitCode);
