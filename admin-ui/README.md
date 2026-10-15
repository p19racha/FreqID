# FreqID Admin Dashboard (`freqid-admin-ui`)

Production web administration dashboard for **FreqID**, the privacy-preserving self-hosted biometric face recognition system.

The dashboard provides system administrators, fleet operators, and compliance officers with an intuitive interface to manage edge camera hardware, audit biometric verifications, govern administrative roles, and enforce GDPR compliance data subject rights.

---

## Core Privacy Guarantees (Hard Rules)

1. **Zero Spatial Biometrics / Camera Capture**:
   - The browser never accesses the camera, video feeds, or raw face images.
   - Enrollment and face recognition happen exclusively on paired physical edge devices running `freqid-client`.
   - Automated CI check (`pnpm check:no-camera`) enforces that `getUserMedia`, `<video>` capture, and file upload inputs accepting images are strictly absent from the source code.
2. **Volatile In-Memory Session Security**:
   - Access tokens are stored exclusively in volatile JavaScript runtime memory (`src/auth/authStore.ts`).
   - Refresh tokens are delivered via `HttpOnly; SameSite=Lax` cookies, shielding them against cross-site scripting (XSS).
   - Zero secrets or tokens are ever written to `localStorage` or `sessionStorage`.
3. **Single-Use Ephemeral Secrets**:
   - Pairing tokens and temporary passwords are displayed exactly once in modal dialogs with a live countdown timer.
   - Closing the dialog purges the secret from client-side state immediately.
4. **Strict RBAC Synchronization**:
   - Front-end permission matrices strictly mirror backend definitions from `freqid_server/auth/permissions.py`. Automated tests fail if role privileges drift.

---

## Tech Stack

- **Framework**: React 18 + Vite 6 + TypeScript (Strict Mode)
- **Styling**: Tailwind CSS + shadcn/ui (Radix UI primitives)
- **Routing**: React Router v6 (layout-nested protected routes)
- **Server State**: TanStack Query v5 (deduplication, background polling, stale cache invalidation)
- **Data Tables**: TanStack Table v8 (accessible, sorting, column visibility)
- **Charts & Telemetry**: Recharts (verification volume, system load metrics)
- **Typed API Client**: `openapi-fetch` + `openapi-typescript` generated from backend `openapi.json`
- **Testing**:
  - Unit & Integration: Vitest + React Testing Library + MSW (Mock Service Worker)
  - End-to-End: Playwright (Chromium headless browser)

---

## Project Structure

```
admin-ui/
├── e2e/                     # Playwright end-to-end test suite
│   └── admin-flows.spec.ts  # Hard rule verification (zero camera, zero web storage)
├── public/
│   ├── config.js            # Runtime API endpoint configuration placeholder
│   └── favicon.svg          # FreqID shield icon
├── scripts/
│   ├── check-api-drift.js   # Verifies v1.d.ts matches backend/openapi.json
│   └── check-no-camera.js   # AST & regex scan forbidding camera/image upload APIs
├── src/
│   ├── api/                 # Typed openapi-fetch client, error parser, models
│   ├── auth/                # In-memory authStore, AuthContext, ProtectedRoute, RBAC matrix
│   ├── components/          # AppShell, Sidebar, Topbar, ThemeToggle, shadcn/ui primitives
│   ├── features/            # Feature modules
│   │   ├── account/         # My account profile, password change, TOTP enrollment
│   │   ├── admins/          # Admin accounts, invite wizard, role assignment (Owner only)
│   │   ├── audit/           # Forensic audit log, filter drawer, CSV export
│   │   ├── dashboard/       # Fleet overview, verification traffic charts, health metrics
│   │   ├── devices/         # Device fleet table, pairing wizard, immediate revocation
│   │   ├── settings/        # System configuration, matching threshold, model params
│   │   ├── status/          # Vector gallery telemetry, memory usage, CPU load
│   │   └── users/           # Identity registry, GDPR Art. 15 export, Art. 17 deletion
│   ├── lib/                 # Utility helpers, date & number formatters
│   ├── routes/              # Top-level route pages (Login, 404)
│   └── test/                # Test setup, MSW mock handlers, unit & integration tests
├── Dockerfile               # Multi-stage unprivileged Nginx build
├── nginx.conf               # Production Nginx server with strict security headers
└── package.json
```

---

## Development & Testing Commands

### Setup
```bash
# Install dependencies with frozen lockfile
pnpm install
```

### Local Development
```bash
# Starts local Vite development server with proxying to backend at :8000
pnpm dev
```

### Code Quality & Security Audits
```bash
# TypeScript compiler type check
pnpm typecheck

# ESLint linting
pnpm lint

# Enforce Hard Rule 1: Zero camera or image handling in browser
pnpm check:no-camera

# Enforce schema parity: Verify no drift against backend/openapi.json
pnpm check:api
```

### Automated Tests
```bash
# Run unit and integration tests (Vitest + MSW)
pnpm test

# Run end-to-end tests against built static bundle (Playwright)
pnpm test:e2e
```

### Production Build
```bash
# Compiles optimized production bundle into dist/
pnpm build
```

---

## Container Deployment

The application includes a multi-stage Docker build producing an unprivileged Alpine Nginx image ($\approx 25\text{ MB}$):

```bash
# Build Docker image
docker build -t freqid-admin-ui .

# Run container (listening on port 8080)
docker run -p 8080:8080 \
  -e FREQID_API_URL="https://api.freqid.internal" \
  freqid-admin-ui
```

### Runtime Configuration
The container's entrypoint script dynamically injects `FREQID_API_URL` into `/usr/share/nginx/html/config.js` on startup, allowing the same container image to be promoted across staging and production without rebuilding.

### Security Headers
The production Nginx configuration enforces defense-in-depth:
- `Content-Security-Policy: default-src 'self'; ...; frame-ancestors 'none';`
- `Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()`
- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
