#!/usr/bin/env node
// check-architecture.js — Block upward layer imports in generated code
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

// Layer rank mapping (lower = more foundational)
const LAYER_RANK = {
  types: 0,
  models: 0,
  schemas: 0,
  config: 1,
  repository: 2,
  db: 2,
  persistence: 2,
  service: 3,
  domain: 3,
  api: 4,
  routes: 4,
  handlers: 4,
  ui: 5,
  frontend: 5,
  components: 5,
};

const layerNames = Object.keys(LAYER_RANK);

// Recursively collect .py/.js/.ts files from a directory
function collectFiles(dir) {
  const results = [];
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return results;
  }
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...collectFiles(full));
    } else if (/\.(py|js|ts)$/.test(entry.name)) {
      results.push(full);
    }
  }
  return results;
}

const searchDirs = [
  path.join(projectRoot, "src"),
  path.join(projectRoot, "migrated_code"),
];

const files = [];
for (const dir of searchDirs) {
  files.push(...collectFiles(dir));
}

for (const filepath of files) {
  // Determine this file's layer from its path
  let fileLayer = null;
  let fileRank = 99;
  for (const layer of layerNames) {
    if (filepath.includes(`/${layer}/`)) {
      fileLayer = layer;
      fileRank = LAYER_RANK[layer];
      break;
    }
  }
  if (fileLayer === null) continue; // Not in a recognized layer

  // Read file and check imports
  let content;
  try {
    content = fs.readFileSync(filepath, "utf8");
  } catch {
    continue;
  }

  const lines = content.split("\n");
  for (const line of lines) {
    if (!/^(from|import) /.test(line)) continue;

    for (const targetLayer of layerNames) {
      const targetRank = LAYER_RANK[targetLayer];
      if (targetRank > fileRank) {
        const pattern = new RegExp(
          `from.*\\b${targetLayer}\\b.*import|import.*\\b${targetLayer}\\b`
        );
        if (pattern.test(line)) {
          console.log(
            `[architecture] BLOCKED: ${filepath} imports from '${targetLayer}' (rank ${targetRank}) but is in '${fileLayer}' (rank ${fileRank})`
          );
          console.log(
            "  Fix: Move code to correct layer or extract shared type to Types layer"
          );
          exitCode = 1;
        }
      }
    }
  }
}

process.exit(exitCode);
