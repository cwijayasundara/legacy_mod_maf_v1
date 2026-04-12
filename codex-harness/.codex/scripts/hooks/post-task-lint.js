#!/usr/bin/env node
// post-task-lint.js — Post-task hook: lint and typecheck migrated code
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

let exitCode = 0;

// Find recently modified files
let changedFiles = "";
try {
  changedFiles = execFileSync(
    "git",
    ["diff", "--name-only", "--diff-filter=ACM", "HEAD"],
    { encoding: "utf8", cwd: projectRoot }
  ).trim();
} catch {
  // Fallback: find files in azure-functions directory
  const azDir = path.join(projectRoot, "src", "azure-functions");
  function findFiles(dir, exts) {
    const results = [];
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return results;
    }
    for (const e of entries) {
      const full = path.join(dir, e.name);
      if (e.isDirectory()) results.push(...findFiles(full, exts));
      else if (exts.some((ext) => e.name.endsWith(ext))) results.push(full);
    }
    return results;
  }
  changedFiles = findFiles(azDir, [".py", ".js", ".ts", ".java", ".cs"]).join(
    "\n"
  );
}

if (!changedFiles) {
  console.log("[hook:lint] No changed files to lint.");
  process.exit(0);
}

const allFiles = changedFiles.split("\n").filter(Boolean);

// Python linting
const pyFiles = allFiles.filter((f) => f.endsWith(".py"));
if (pyFiles.length > 0) {
  console.log("[hook:lint] Linting Python files...");
  try {
    execFileSync("which", ["ruff"]);
    try {
      execFileSync("ruff", ["check", "--fix", ...pyFiles], {
        stdio: "inherit",
        cwd: projectRoot,
      });
    } catch {
      exitCode = 1;
    }
  } catch {
    // ruff not available
  }

  try {
    execFileSync("which", ["mypy"]);
    try {
      execFileSync("mypy", ["--ignore-missing-imports", ...pyFiles], {
        stdio: "inherit",
        cwd: projectRoot,
      });
    } catch {
      console.warn("[hook:typecheck] WARNING: mypy found type errors");
      // Warn but don't block for type errors during migration
    }
  } catch {
    // mypy not available
  }
}

// Node.js linting
const jsFiles = allFiles.filter((f) => /\.(js|ts)$/.test(f));
if (jsFiles.length > 0) {
  console.log("[hook:lint] Linting Node.js files...");
  try {
    execFileSync("which", ["eslint"]);
    try {
      execFileSync("eslint", ["--fix", ...jsFiles], {
        stdio: "inherit",
        cwd: projectRoot,
      });
    } catch {
      exitCode = 1;
    }
  } catch {
    // eslint not available
  }
}

// Java check
const javaFiles = allFiles.filter((f) => f.endsWith(".java"));
if (javaFiles.length > 0) {
  console.log("[hook:lint] Checking Java files...");
  try {
    execFileSync("which", ["javac"]);
    console.log(
      "[hook:lint] Java files detected -- verify compilation via build tool."
    );
  } catch {
    // javac not available
  }
}

if (exitCode !== 0) {
  console.log("[hook:lint] BLOCKED: lint errors found. Fix before committing.");
}

process.exit(exitCode);
