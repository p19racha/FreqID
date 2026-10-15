# syntax=docker/dockerfile:1
# Copyright 2026 FreqID Authors. Apache-2.0 License.
# Hardened Multi-Stage Production Dockerfile for FreqID Admin Web UI

# ==============================================================================
# Stage 1: Production TypeScript & React Build
# ==============================================================================
FROM node:20.18.0-alpine AS builder

WORKDIR /app

# Install pnpm with strict version pin
RUN npm install -g pnpm@10.27.0

# Copy package manifests and lockfile for deterministic dependency caching
COPY package.json pnpm-lock.yaml ./

# Install dependencies strictly matching the lockfile
RUN pnpm install --frozen-lockfile

# Copy application configuration and source files
COPY tsconfig.json tailwind.config.js postcss.config.js vite.config.ts eslint.config.js components.json index.html ./
COPY src/ ./src/
COPY public/ ./public/
COPY scripts/ ./scripts/

# Verify strict Hard Rule 1 (zero camera capture) and compile production bundle
RUN pnpm check:no-camera && pnpm build

# ==============================================================================
# Stage 2: Hardened Unprivileged Nginx Static Serving
# ==============================================================================
FROM nginxinc/nginx-unprivileged:1.27.4-alpine AS runner

# OCI Standard Metadata Labels
LABEL org.opencontainers.image.title="freqid-admin-ui" \
      org.opencontainers.image.description="FreqID Admin Web UI Dashboard" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.vendor="FreqID Authors" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://github.com/p19racha/FreqID"

USER root

# Configure Nginx and runtime configuration script
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Copy compiled SPA assets from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html
RUN chown -R 101:101 /usr/share/nginx/html /etc/nginx/conf.d

# Drop all privileges - run as unprivileged nginx user (UID 101)
USER 101:101

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD wget --quiet --tries=1 --spider http://127.0.0.1:8080/ || exit 1

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
