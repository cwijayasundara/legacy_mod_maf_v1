#!/usr/bin/env node
// migrate-batch.js — Run migration pipeline for multiple modules
// Supports parallel execution across independent modules (leaves-first ordering).
//
// Usage:
//   ./.codex/scripts/migrate-batch.js [--parallel N] [modules-file]
//
// The modules file is a TSV with columns:
//   module-name  language  work-item-id  depends-on
//
// depends-on is a comma-separated list of modules that must complete first.
// Empty means no dependencies (leaf module -- can run immediately).

"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");

const SCRIPT_DIR = __dirname;
const PROJECT_ROOT = path.resolve(SCRIPT_DIR, "..", "..");

// --- Parse arguments ---
let maxParallel = 3;
let modulesFile = "";

const argv = process.argv.slice(2);
for (let i = 0; i < argv.length; i++) {
  if (argv[i] === "--parallel" && argv[i + 1]) {
    maxParallel = parseInt(argv[i + 1], 10);
    i++;
  } else {
    modulesFile = argv[i];
  }
}

if (!modulesFile) {
  modulesFile = path.join(SCRIPT_DIR, "modules.tsv");
}

if (!fs.existsSync(modulesFile)) {
  console.error(`ERROR: Modules file not found: ${modulesFile}`);
  console.error(
    "Create a TSV file with columns: module-name  language  work-item-id  [depends-on]"
  );
  process.exit(1);
}

// --- Parse module list ---
const modules = []; // ordered list of module names
const modLang = {};
const modWi = {};
const modDeps = {};
const modStatus = {};

const tsvContent = fs.readFileSync(modulesFile, "utf8");
for (const line of tsvContent.split("\n")) {
  const trimmed = line.trim();
  if (!trimmed || trimmed.startsWith("#")) continue;
  const parts = trimmed.split("\t");
  const mod = parts[0];
  const lang = parts[1] || "";
  const wi = parts[2] || "";
  const deps = parts[3] || "";
  modules.push(mod);
  modLang[mod] = lang;
  modWi[mod] = wi;
  modDeps[mod] = deps;
  modStatus[mod] = "pending";
}

const TOTAL = modules.length;
const MAX_CONSECUTIVE_BLOCKED = 3;

console.log(
  "+==================================================================="
);
console.log(
  `|  Batch Migration -- ${TOTAL} modules (max ${maxParallel} parallel)`
);
console.log(
  "+==================================================================="
);
console.log("");

// --- DAG-based execution ---
let passed = 0;
let failed = 0;
let blocked = 0;
let consecutiveBlocked = 0;
let scheduled = 0;

// Running jobs: { module, childProcess, promise }
const running = [];

function checkDepsMet(mod) {
  const deps = modDeps[mod];
  if (!deps) return true;
  const depList = deps.split(",").map((d) => d.trim()).filter(Boolean);
  return depList.every((d) => modStatus[d] === "completed");
}

function checkDepsBlocked(mod) {
  const deps = modDeps[mod];
  if (!deps) return false;
  const depList = deps.split(",").map((d) => d.trim()).filter(Boolean);
  return depList.some(
    (d) => modStatus[d] === "failed" || modStatus[d] === "blocked"
  );
}

function spawnModule(mod) {
  return new Promise((resolve) => {
    const child = spawn(
      process.execPath,
      [path.join(SCRIPT_DIR, "migrate-module.js"), mod, modLang[mod], modWi[mod]],
      {
        cwd: PROJECT_ROOT,
        stdio: "inherit",
      }
    );
    child.on("close", (code) => {
      resolve({ mod, code: code || 0 });
    });
    child.on("error", () => {
      resolve({ mod, code: 1 });
    });
  });
}

function handleCompletion(mod, code) {
  if (code === 0) {
    const blockedFile = path.join(
      PROJECT_ROOT,
      "migration-analysis",
      mod,
      "blocked.md"
    );
    if (fs.existsSync(blockedFile)) {
      modStatus[mod] = "blocked";
      blocked++;
      consecutiveBlocked++;
      console.log(`[!!] ${mod}: BLOCKED (see blocked.md)`);
    } else {
      modStatus[mod] = "completed";
      passed++;
      consecutiveBlocked = 0;
      console.log(`[ok] ${mod}: PASSED`);
    }
  } else {
    modStatus[mod] = "failed";
    failed++;
    consecutiveBlocked++;
    console.log(`[xx] ${mod}: FAILED (exit code ${code})`);
  }

  if (consecutiveBlocked >= MAX_CONSECUTIVE_BLOCKED) {
    console.log("");
    console.log(
      `STOPPING: ${consecutiveBlocked} consecutive blocked/failed modules.`
    );
    console.log(
      "This indicates a systemic issue. Check state/learned-rules.md and program.md."
    );
    return true; // signal stop
  }
  return false;
}

function printSummary() {
  console.log("");
  console.log("===================================================================");
  console.log("Batch Migration Summary");
  console.log(`  Total:   ${TOTAL}`);
  console.log(`  Passed:  ${passed}`);
  console.log(`  Blocked: ${blocked}`);
  console.log(`  Failed:  ${failed}`);
  console.log("");
  console.log("Module Status:");
  for (const mod of modules) {
    console.log(`  ${mod}: ${modStatus[mod]}`);
  }
  console.log("===================================================================");
}

async function main() {
  let shouldStop = false;

  while (scheduled < TOTAL && !shouldStop) {
    let madeProgress = false;

    for (const mod of modules) {
      if (shouldStop) break;
      if (modStatus[mod] !== "pending") continue;

      // If dependencies are blocked/failed, mark as blocked
      if (checkDepsBlocked(mod)) {
        modStatus[mod] = "blocked";
        blocked++;
        consecutiveBlocked++;
        scheduled++;
        console.log(`[!!] ${mod}: BLOCKED (dependency failed)`);
        if (consecutiveBlocked >= MAX_CONSECUTIVE_BLOCKED) {
          console.log("");
          console.log(
            `STOPPING: ${consecutiveBlocked} consecutive blocked/failed modules.`
          );
          shouldStop = true;
          break;
        }
        madeProgress = true;
        continue;
      }

      if (!checkDepsMet(mod)) continue;

      // Wait if at max parallel
      while (running.length >= maxParallel) {
        const result = await Promise.race(running.map((r) => r.promise));
        const idx = running.findIndex((r) => r.mod === result.mod);
        if (idx !== -1) running.splice(idx, 1);
        shouldStop = handleCompletion(result.mod, result.code);
        if (shouldStop) break;
      }

      if (shouldStop) break;

      console.log("--------------------------------------------------------------------");
      console.log(
        `[${scheduled + 1}/${TOTAL}] Starting: ${mod} (${modLang[mod]}) -- ${modWi[mod]}`
      );
      console.log("--------------------------------------------------------------------");

      modStatus[mod] = "running";
      const promise = spawnModule(mod);
      running.push({ mod, promise });
      scheduled++;
      madeProgress = true;
    }

    if (!madeProgress && !shouldStop) {
      if (running.length > 0) {
        const result = await Promise.race(running.map((r) => r.promise));
        const idx = running.findIndex((r) => r.mod === result.mod);
        if (idx !== -1) running.splice(idx, 1);
        shouldStop = handleCompletion(result.mod, result.code);
      } else {
        console.error(
          "ERROR: Deadlock -- modules have unresolvable dependencies"
        );
        break;
      }
    }
  }

  // Wait for remaining jobs
  for (const job of running) {
    const result = await job.promise;
    handleCompletion(result.mod, result.code);
  }

  printSummary();

  if (failed > 0 || shouldStop) {
    process.exit(1);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
