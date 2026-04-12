#!/usr/bin/env node
// setup.js — One-time setup for the migration harness on your local machine
//
// Prerequisites:
//   - Node.js 18+ (for Codex CLI)
//   - Python 3.11+ (for Azure Functions trigger)
//   - Git

"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

console.log(
  "+==================================================================="
);
console.log(
  "|  Migration Harness -- Local Setup"
);
console.log(
  "+==================================================================="
);
console.log("");

const SCRIPT_DIR = __dirname;
const PROJECT_ROOT = path.resolve(SCRIPT_DIR, "..", "..");

// --- 1. Check prerequisites ---
console.log("Checking prerequisites...");

let missing = false;

function checkCmd(name, hint) {
  try {
    const loc = execFileSync("which", [name], { encoding: "utf8" }).trim();
    console.log(`  [ok] ${name}: ${loc}`);
  } catch {
    console.log(`  [xx] ${name}: NOT FOUND -- ${hint}`);
    missing = true;
  }
}

checkCmd("node", "Install from https://nodejs.org (v18+)");
checkCmd("npm", "Comes with Node.js");
checkCmd("python3", "Install Python 3.11+");
checkCmd("git", "Install git");

if (missing) {
  console.log("");
  console.error("ERROR: Missing prerequisites. Install the above tools first.");
  process.exit(1);
}
console.log("");

// --- 2. Install Codex CLI ---
console.log("Installing Codex CLI...");
try {
  execFileSync("which", ["codex"]);
  let version = "installed";
  try {
    version = execFileSync("codex", ["--version"], {
      encoding: "utf8",
    }).trim();
  } catch {
    // version flag might not exist
  }
  console.log(`  [ok] Codex CLI already installed: ${version}`);
} catch {
  execFileSync("npm", ["install", "-g", "@openai/codex"], {
    stdio: "inherit",
  });
  console.log("  [ok] Codex CLI installed");
}
console.log("");

// --- 3. Install Azure Functions Core Tools (optional) ---
console.log("Installing Azure Functions Core Tools...");
try {
  execFileSync("which", ["func"]);
  console.log("  [ok] Azure Functions Core Tools already installed");
} catch {
  console.log("  -> Installing via npm...");
  try {
    execFileSync(
      "npm",
      ["install", "-g", "azure-functions-core-tools@4", "--unsafe-perm", "true"],
      { stdio: "inherit" }
    );
    console.log("  [ok] Azure Functions Core Tools installed");
  } catch {
    console.warn(
      "  [!!] Failed to install Azure Functions Core Tools. Install manually if needed."
    );
  }
}
console.log("");

// --- 4. Check OpenAI API Key ---
console.log("Checking authentication...");
if (process.env.OPENAI_API_KEY) {
  console.log("  [ok] OPENAI_API_KEY is set");
} else {
  console.log("  [!!] OPENAI_API_KEY not set.");
  console.log("    Option A: export OPENAI_API_KEY=sk-...");
  console.log(
    "    Option B: Run 'codex' and sign in with your ChatGPT account"
  );
}
console.log("");

// --- 5. Initialize git repo ---
console.log("Initializing git repository...");
const gitDir = path.join(PROJECT_ROOT, ".git");
if (fs.existsSync(gitDir)) {
  console.log("  [ok] Git repo already initialized");
} else {
  execFileSync("git", ["init"], { cwd: PROJECT_ROOT, stdio: "inherit" });
  console.log("  [ok] Git repo initialized");
}
console.log("");

// --- 6. Make scripts executable ---
console.log("Making scripts executable...");
const scriptsDir = path.join(PROJECT_ROOT, ".codex", "scripts");
function makeExecutable(dir) {
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      makeExecutable(full);
    } else if (entry.name.endsWith(".js")) {
      fs.chmodSync(full, 0o755);
    }
  }
}
makeExecutable(scriptsDir);
console.log("  [ok] Done");
console.log("");

// --- 7. Install trigger function dependencies ---
console.log("Installing trigger function dependencies...");
const triggerDir = path.join(PROJECT_ROOT, "trigger");
const reqFile = path.join(triggerDir, "requirements.txt");
if (fs.existsSync(reqFile)) {
  try {
    execFileSync(
      "python3",
      ["-m", "pip", "install", "-r", reqFile, "--quiet"],
      { cwd: triggerDir, stdio: "inherit" }
    );
    console.log("  [ok] Python dependencies installed");
  } catch {
    console.warn("  [!!] Failed to install Python dependencies");
  }
} else {
  console.log("  [--] No requirements.txt found in trigger/");
}
console.log("");

// --- Summary ---
console.log("===================================================================");
console.log("Setup complete! Next steps:");
console.log("");
console.log("  1. Set your OpenAI API key (if not done):");
console.log("     export OPENAI_API_KEY=sk-...");
console.log("");
console.log("  2. Test with a single module:");
console.log(
  "     ./.codex/scripts/migrate-module.js order-processor python WI-1001"
);
console.log("");
console.log("  3. Run batch migration:");
console.log("     ./.codex/scripts/migrate-batch.js");
console.log("");
console.log("  4. (Optional) Start the trigger function locally:");
console.log("     cd trigger && func start");
console.log("");
console.log("===================================================================");
