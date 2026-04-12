#!/usr/bin/env node
// typecheck.js — Run mypy (Python) or tsc (TypeScript) on changed files
"use strict";

const fs = require("node:fs");
const { execFileSync } = require("node:child_process");

const filePaths = process.argv.slice(2);

for (const filepath of filePaths) {
  if (!fs.existsSync(filepath)) continue;

  if (filepath.endsWith(".py")) {
    try {
      execFileSync("which", ["mypy"]);
    } catch {
      continue;
    }
    console.log(`[typecheck] Checking ${filepath}...`);
    try {
      execFileSync(
        "mypy",
        ["--ignore-missing-imports", "--no-error-summary", filepath],
        { stdio: "inherit" }
      );
    } catch {
      console.warn(`[typecheck] WARNING: Type errors in ${filepath}`);
    }
  } else if (filepath.endsWith(".ts")) {
    try {
      execFileSync("which", ["tsc"]);
    } catch {
      continue;
    }
    console.log(`[typecheck] Checking ${filepath}...`);
    try {
      execFileSync("tsc", ["--noEmit", filepath], { stdio: "inherit" });
    } catch {
      console.warn(`[typecheck] WARNING: Type errors in ${filepath}`);
    }
  }
}
