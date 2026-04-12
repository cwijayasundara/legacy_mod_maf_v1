#!/usr/bin/env node
// check-function-length.js — Warn on functions >50 lines, block >100
"use strict";

const fs = require("node:fs");

const WARN_THRESHOLD = 50;
const BLOCK_THRESHOLD = 100;
let exitCode = 0;

const filePaths = process.argv.slice(2);

for (const filepath of filePaths) {
  if (!fs.existsSync(filepath)) continue;

  let pattern;
  if (filepath.endsWith(".py")) {
    pattern = /^\s*(async\s+)?def\s+/;
  } else if (filepath.endsWith(".js") || filepath.endsWith(".ts")) {
    pattern =
      /^\s*(async\s+)?function\s+|^\s*(const|let)\s+\w+\s*=.*=>/;
  } else if (filepath.endsWith(".java") || filepath.endsWith(".cs")) {
    pattern =
      /^\s*(public|private|protected|static|\s)+([\w<>\[\]]+\s+\w+\s*\()/;
  } else {
    continue;
  }

  const content = fs.readFileSync(filepath, "utf8");
  const lines = content.split("\n");

  // Collect line numbers where functions start (1-based)
  const funcStarts = [];
  for (let i = 0; i < lines.length; i++) {
    if (pattern.test(lines[i])) {
      funcStarts.push(i + 1); // 1-based
    }
  }
  // Sentinel for measuring the last function
  funcStarts.push(99999);

  for (let i = 0; i < funcStarts.length - 1; i++) {
    const lineNum = funcStarts[i];
    const nextLineNum = funcStarts[i + 1];
    const length = nextLineNum - lineNum;
    const funcName = lines[lineNum - 1].trim().substring(0, 60);

    if (length > BLOCK_THRESHOLD) {
      console.log(
        `[function-length] BLOCKED: ${filepath}:${lineNum} -- '${funcName}' is ${length} lines (max ${BLOCK_THRESHOLD})`
      );
      exitCode = 1;
    } else if (length > WARN_THRESHOLD) {
      console.warn(
        `[function-length] WARNING: ${filepath}:${lineNum} -- '${funcName}' is ${length} lines (consider splitting at ${WARN_THRESHOLD})`
      );
    }
  }
}

process.exit(exitCode);
