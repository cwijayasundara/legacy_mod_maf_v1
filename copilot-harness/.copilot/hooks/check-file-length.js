#!/usr/bin/env node
// check-file-length.js — Warn on files >200 lines, block >300
"use strict";

const fs = require("node:fs");

const WARN_THRESHOLD = 200;
const BLOCK_THRESHOLD = 300;
let exitCode = 0;

const filePaths = process.argv.slice(2);

for (const filepath of filePaths) {
  if (!fs.existsSync(filepath)) continue;

  const content = fs.readFileSync(filepath, "utf8");
  const lines = content.split("\n").length;

  if (lines > BLOCK_THRESHOLD) {
    console.log(
      `[file-length] BLOCKED: ${filepath} is ${lines} lines (max ${BLOCK_THRESHOLD})`
    );
    console.log("  Fix: Split into sub-modules with single responsibility");
    exitCode = 1;
  } else if (lines > WARN_THRESHOLD) {
    console.warn(
      `[file-length] WARNING: ${filepath} is ${lines} lines (consider splitting at ${WARN_THRESHOLD})`
    );
  }
}

process.exit(exitCode);
