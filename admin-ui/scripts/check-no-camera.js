#!/usr/bin/env node
// Copyright 2026 FreqID Authors. Apache-2.0 License.
/**
 * check-no-camera.js: Enforces Hard Rule 1.
 * Scans all source files under src/ to ensure the admin UI never captures,
 * displays, uploads or stores face images, and never uses browser camera APIs.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const srcDir = path.resolve(__dirname, "../src");

const FORBIDDEN_PATTERNS = [
  { pattern: /getUserMedia/i, reason: "Browser camera capture (getUserMedia) is strictly forbidden." },
  { pattern: /navigator\.mediaDevices/i, reason: "Accessing media devices is strictly forbidden." },
  { pattern: /<video/i, reason: "<video> elements for camera feed are strictly forbidden." },
  { pattern: /accept\s*=\s*["'].*image/i, reason: "Image file upload inputs are strictly forbidden." },
  { pattern: /PartialFacePayload/i, reason: "Raw partial frequency payloads must not be processed in browser UI." },
  { pattern: /canvas\.toDataURL/i, reason: "Canvas image serialization is forbidden in admin UI." },
];

function scanDirectory(dir) {
  let violations = [];
  const entries = fs.readdirSync(dir, { withFileTypes: true });

  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      violations = violations.concat(scanDirectory(fullPath));
    } else if (entry.isFile() && /\.(tsx?|jsx?|html)$/.test(entry.name)) {
      const content = fs.readFileSync(fullPath, "utf-8");
      const lines = content.split("\n");

      lines.forEach((line, index) => {
        for (const rule of FORBIDDEN_PATTERNS) {
          if (rule.pattern.test(line)) {
            violations.push({
              file: path.relative(srcDir, fullPath),
              line: index + 1,
              code: line.trim(),
              reason: rule.reason,
            });
          }
        }
      });
    }
  }

  return violations;
}

const violations = scanDirectory(srcDir);

if (violations.length > 0) {
  console.error("\n❌ [FAIL] Hard Rule 1 Violation Detected: Camera/Image API found in UI source!");
  console.error("==========================================================================");
  for (const v of violations) {
    console.error(`  - ${v.file}:${v.line}: ${v.reason}`);
    console.error(`    Line: "${v.code}"`);
  }
  console.error("==========================================================================\n");
  process.exit(1);
} else {
  console.log("✅ [PASS] Hard Rule 1 Verified: Zero camera, video capture, or image upload APIs in UI.");
}
