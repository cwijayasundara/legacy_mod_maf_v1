#!/usr/bin/env node
// pre-commit-gate.js — Pre-commit hook: enforce quality gates before any commit
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

let projectRoot = process.env.PROJECT_ROOT;
if (!projectRoot) {
  try {
    projectRoot = execFileSync("git", ["rev-parse", "--show-toplevel"], {
      encoding: "utf8",
    }).trim();
  } catch {
    projectRoot = process.cwd();
  }
}

let staged = "";
try {
  staged = execFileSync(
    "git",
    ["diff", "--cached", "--name-only", "--diff-filter=ACM"],
    { encoding: "utf8", cwd: projectRoot }
  ).trim();
} catch {
  staged = "";
}

if (!staged) {
  process.exit(0);
}

const stagedFiles = staged.split("\n").filter(Boolean);
let exitCode = 0;

console.log("[gate] Running pre-commit quality gates...");

// --- Gate 1: No AWS SDK imports in azure-functions/ ---
const azureFiles = stagedFiles.filter((f) =>
  f.includes("src/azure-functions/")
);
if (azureFiles.length > 0) {
  console.log("[gate:aws-artifacts] Checking for remaining AWS imports...");
  const awsPattern = /boto3|@aws-sdk|AWSSDK\.|com\.amazonaws/;
  const awsImports = [];
  for (const f of azureFiles) {
    const fullPath = path.join(projectRoot, f);
    try {
      const content = fs.readFileSync(fullPath, "utf8");
      if (awsPattern.test(content)) {
        awsImports.push(f);
      }
    } catch {
      // skip unreadable files
    }
  }
  if (awsImports.length > 0) {
    console.log(
      "[gate:aws-artifacts] BLOCKED: AWS SDK imports found in migrated code:"
    );
    console.log(awsImports.join("\n"));
    console.log(
      "Fix: Replace all AWS SDK imports with Azure SDK equivalents."
    );
    exitCode = 1;
  }
}

// --- Gate 2: No secrets in code ---
console.log("[gate:secrets] Scanning for hardcoded secrets...");
const secretPattern =
  /(api[_-]?key|password|secret|token|credential)\s*[:=]\s*["'][A-Za-z0-9+/=]{8,}/i;
const secretsFound = [];
for (const f of stagedFiles) {
  const fullPath = path.join(projectRoot, f);
  try {
    const content = fs.readFileSync(fullPath, "utf8");
    if (secretPattern.test(content)) {
      secretsFound.push(f);
    }
  } catch {
    // skip
  }
}
if (secretsFound.length > 0) {
  console.log("[gate:secrets] BLOCKED: Possible hardcoded secrets found:");
  console.log(secretsFound.join("\n"));
  console.log("Fix: Use environment variables or Azure Key Vault references.");
  exitCode = 1;
}

// --- Gate 3: Coverage ratchet ---
const baselineFile = path.join(projectRoot, "state", "coverage-baseline.txt");
if (fs.existsSync(baselineFile)) {
  const baselineContent = fs.readFileSync(baselineFile, "utf8");
  const match = baselineContent.match(/^(\d+)/m);
  if (match) {
    console.log(`[gate:coverage] Coverage baseline: ${match[1]}%`);
    console.log(
      "[gate:coverage] NOTE: Actual coverage check runs during tester agent phase."
    );
  }
}

// --- Gate 4: No modifications to protected paths ---
const protectedPattern = /^(src\/lambda\/|\.codex\/config\.toml)/;
const protectedModified = stagedFiles.filter((f) => protectedPattern.test(f));
if (protectedModified.length > 0) {
  console.log(
    "[gate:protected] BLOCKED: Attempted modification of protected paths:"
  );
  console.log(protectedModified.join("\n"));
  console.log(
    "Fix: src/lambda/ is read-only reference. .codex/config.toml requires manual edit."
  );
  exitCode = 1;
}

// --- Gate 5: Reviewer verdict exists for module being committed ---
const modulesCommitted = [
  ...new Set(
    azureFiles
      .map((f) => {
        const m = f.match(/src\/azure-functions\/([^/]+)\//);
        return m ? m[1] : null;
      })
      .filter(Boolean)
  ),
];
for (const mod of modulesCommitted) {
  const reviewPath = path.join(
    projectRoot,
    "migration-analysis",
    mod,
    "review.md"
  );
  if (!fs.existsSync(reviewPath)) {
    console.log(
      `[gate:review] BLOCKED: No review.md found for module '${mod}'.`
    );
    console.log(
      "Fix: Run the migration-reviewer agent before committing."
    );
    exitCode = 1;
  } else {
    const reviewContent = fs.readFileSync(reviewPath, "utf8");
    if (!reviewContent.includes("APPROVE")) {
      console.log(
        `[gate:review] BLOCKED: Reviewer did not APPROVE module '${mod}'.`
      );
      console.log(
        "Fix: Address reviewer feedback and re-run the reviewer agent."
      );
      exitCode = 1;
    }
  }
}

// --- Gate 6: Sprint contract exists for module ---
for (const mod of modulesCommitted) {
  const contractPath = path.join(
    projectRoot,
    "migration-analysis",
    mod,
    "sprint-contract.json"
  );
  if (!fs.existsSync(contractPath)) {
    console.log(
      `[gate:contract] WARNING: No sprint-contract.json for module '${mod}'.`
    );
    console.log(
      "Fix: Run contract negotiation between coder and reviewer before implementation."
    );
  }
}

if (exitCode !== 0) {
  console.log("");
  console.log("[gate] COMMIT BLOCKED -- fix the issues above.");
} else {
  console.log("[gate] All pre-commit gates passed.");
}

process.exit(exitCode);
