// Copyright 2026 FreqID Authors. Apache-2.0 License.
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { ROLE_PERMISSIONS, PERMISSIONS } from "@/auth/permissions";

describe("RBAC Permissions Drift Check", () => {
  it("strictly mirrors backend ROLE_PERMISSIONS without drift", () => {
    // Read the Python permissions source file from backend
    const pythonPermsPath = path.resolve(
      __dirname,
      "../../../backend/src/freqid_server/auth/permissions.py"
    );

    expect(fs.existsSync(pythonPermsPath)).toBe(true);
    const pythonSource = fs.readFileSync(pythonPermsPath, "utf8");

    // Extract all PERM_* constants from Python
    const permConstants: Record<string, string> = {};
    const permRegex = /^(PERM_[A-Z0-9_]+):\s*Final\s*=\s*"([^"]+)"/gm;
    let match: RegExpExecArray | null;

    while ((match = permRegex.exec(pythonSource)) !== null) {
      permConstants[match[1]] = match[2];
    }

    // Verify all Python permission strings exist in TypeScript PERMISSIONS
    const tsPermValues = new Set(Object.values(PERMISSIONS));
    for (const [, pyVal] of Object.entries(permConstants)) {
      expect(tsPermValues.has(pyVal as any)).toBe(true);
    }

    // Parse role blocks from Python
    const roles: ("owner" | "admin" | "operator" | "auditor")[] = [
      "owner",
      "admin",
      "operator",
      "auditor",
    ];

    for (const role of roles) {
      // Find block for role
      const roleBlockRegex = new RegExp(
        `"${role}":\\s*frozenset\\(\\s*\\{([^}]+)\\}\\s*\\)`,
        "s"
      );
      const roleMatch = roleBlockRegex.exec(pythonSource);
      expect(roleMatch).toBeTruthy();

      const rawPerms = roleMatch![1]
        .split(",")
        .map((p) => p.trim())
        .filter((p) => p.length > 0 && !p.startsWith("#"));

      const expectedPerms = new Set(
        rawPerms.map((p) => {
          const val = permConstants[p];
          if (!val) throw new Error(`Unknown permission constant in python: ${p}`);
          return val;
        })
      );

      const actualTsPerms = ROLE_PERMISSIONS[role];
      expect(actualTsPerms).toBeDefined();

      // Check size equality
      expect(actualTsPerms.size).toBe(expectedPerms.size);

      // Check every permission in Python is in TypeScript
      for (const p of expectedPerms) {
        expect(actualTsPerms.has(p)).toBe(true);
      }

      // Check every permission in TypeScript is in Python
      for (const p of actualTsPerms) {
        expect(expectedPerms.has(p)).toBe(true);
      }
    }
  });
});
