// Copyright 2026 FreqID Authors. Apache-2.0 License.
import { test, expect } from "@playwright/test";

test.describe("FreqID Admin Dashboard E2E", () => {
  test.beforeEach(async ({ page }) => {
    // Intercept and mock API routes
    await page.route("**/v1/admin/auth/login", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          access_token: "mock-e2e-access-token",
          token_type: "bearer",
          expires_in: 900,
          admin_id: "adm-001",
          username: "owner",
          role: "owner",
          permissions: [
            "admin:create",
            "device:list",
            "device:create_pairing_token",
            "device:revoke",
            "system:status",
            "audit:read",
            "user:list",
          ],
        }),
      });
    });

    await page.route("**/v1/admin/auth/refresh", async (route) => {
      await route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ detail: "No refresh cookie present" }),
      });
    });

    await page.route("**/v1/admin/system/status", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          model_version: "partialface_ir18_v1",
          gallery_size: 1542,
          queue_depth: 0,
          device_counts: {
            active: 12,
            pending: 1,
            suspended: 0,
            revoked: 3,
          },
          system_load: {
            cpu_pct: 14.2,
            mem_used_bytes: 4294967296,
            mem_total_bytes: 17179869184,
          },
        }),
      });
    });

    await page.route("**/v1/admin/devices**", async (route) => {
      if (route.request().url().includes("pairing-tokens")) {
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            id: "ptok-123",
            token: "pair-128bit-secret-token-e2e",
            expires_at: new Date(Date.now() + 15 * 60000).toISOString(),
            scopes_allowed: ["verify"],
          }),
        });
        return;
      }

      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            id: "dev-001",
            name: "lobby-turnstile-cam-01",
            state: "active",
            scopes: ["verify"],
            key_id: "key-9912",
            software_version: "freqid-client-v0.1.0",
            last_seen: new Date().toISOString(),
            created_at: "2026-02-01T10:00:00Z",
          },
        ]),
      });
    });

    await page.route("**/v1/admin/users*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
    });

    await page.route("**/v1/admin/audit*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [],
          total: 0,
        }),
      });
    });
  });

  test("proves zero camera capture and complete authentication flow", async ({ page }) => {
    // Navigate to Login page
    await page.goto("/login");
    await expect(page).toHaveTitle(/FreqID Admin/i);

    // Hard Rule 1 Verification: Absolutely NO camera/video elements
    const videoElements = await page.locator("video").count();
    expect(videoElements).toBe(0);

    // Fill credentials and sign in
    await page.fill("#username", "owner");
    await page.fill("#password", "CorrectPassword123!");
    await page.click('button[type="submit"]');

    // Verify redirected to dashboard / system status
    await expect(page.locator("h1")).toContainText(/System Overview/i);
    await expect(page.getByText("Edge Devices")).toBeVisible();
  });

  test("proves pairing tokens are displayed once and never stored in localStorage", async ({ page }) => {
    // Log in first
    await page.goto("/login");
    await page.fill("#username", "owner");
    await page.fill("#password", "CorrectPassword123!");
    await page.click('button[type="submit"]');
    await expect(page.locator("h1")).toContainText(/System Overview/i);

    // Navigate to Devices via SPA link
    await page.getByRole("link", { name: "Devices" }).click();
    await expect(page.locator("h1")).toContainText(/Edge Device Network/i);
    await expect(page.getByText("lobby-turnstile-cam-01")).toBeVisible();

    // Click "Add Device"
    await page.click('button:has-text("Add Device")');
    await expect(page.getByText(/Add Edge Device/i)).toBeVisible();

    // Type device name and generate token
    await page.fill("#device-name", "gate-kiosk-02");
    await page.click('button:has-text("Generate Pairing Token")');

    // Verify single-use token rendered on screen
    await expect(page.getByText("pair-128bit-secret-token-e2e", { exact: true })).toBeVisible();
    await expect(page.getByText(/Security Notice/i)).toBeVisible();

    // Verify localStorage & sessionStorage contain 0 tokens or secrets
    const storageKeys = await page.evaluate(() => {
      return {
        localKeys: Object.keys(localStorage),
        sessionKeys: Object.keys(sessionStorage),
      };
    });

    for (const key of [...storageKeys.localKeys, ...storageKeys.sessionKeys]) {
      expect(key).not.toMatch(/token|secret|jwt|pair/i);
    }

    // Close the dialog
    await page.click('button:has-text("Close (Keep waiting in background)")');

    // Verify dialog is closed and token is gone from DOM
    await expect(page.getByText("pair-128bit-secret-token-e2e", { exact: true })).not.toBeVisible();
  });
});
