#!/usr/bin/env node
// Copyright 2026 FreqID Authors. Apache-2.0 License.
/**
 * check-api-drift.js: Verifies generated API client types match backend openapi.json.
 * Fails if src/api/v1.d.ts is out of date.
 */

import fs from "node:fs";
import path from "node:path";
import { execSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");
const openApiPath = path.resolve(rootDir, "../backend/openapi.json");
const currentTypesPath = path.resolve(rootDir, "src/api/v1.d.ts");
const tempTypesPath = path.resolve(rootDir, "src/api/v1.d.ts.tmp");

if (!fs.existsSync(openApiPath)) {
  console.error(`❌ [FAIL] backend/openapi.json not found at ${openApiPath}`);
  process.exit(1);
}

try {
  // Generate into temp file
  execSync(`pnpm exec openapi-typescript "${openApiPath}" -o "${tempTypesPath}"`, {
    cwd: rootDir,
    stdio: "pipe",
  });

  if (!fs.existsSync(currentTypesPath)) {
    console.error("❌ [FAIL] src/api/v1.d.ts does not exist! Run `pnpm gen:api` first.");
    if (fs.existsSync(tempTypesPath)) fs.unlinkSync(tempTypesPath);
    process.exit(1);
  }

  const currentContent = fs.readFileSync(currentTypesPath, "utf-8");
  const tempContent = fs.readFileSync(tempTypesPath, "utf-8");

  if (currentContent !== tempContent) {
    console.error("❌ [FAIL] Generated API client types are out of date with backend/openapi.json!");
    console.error("Run `pnpm gen:api` to update src/api/v1.d.ts and review git diff.");
    fs.unlinkSync(tempTypesPath);
    process.exit(1);
  }

  fs.unlinkSync(tempTypesPath);
  console.log("✅ [PASS] API client types (src/api/v1.d.ts) match backend/openapi.json perfectly.");
} catch (err) {
  console.error("❌ [FAIL] Error running openapi-typescript check:", err.message);
  if (fs.existsSync(tempTypesPath)) fs.unlinkSync(tempTypesPath);
  process.exit(1);
}
