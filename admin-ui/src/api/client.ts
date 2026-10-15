// Copyright 2026 FreqID Authors. Apache-2.0 License.
/**
 * client.ts: Central typed HTTP client built on openapi-fetch.
 * Handles single-flight token refreshing, Bearer authorization injection,
 * credentials: include for HttpOnly cookies, and structured ApiError mapping.
 */

import createClient from "openapi-fetch";
import type { paths } from "./v1";
import { authStore, AdminUser } from "@/auth/authStore";
import { ApiError } from "./errors";
import { toast } from "sonner";

export function getApiBaseUrl(): string {
  if (typeof window !== "undefined" && window.__FREQID_CONFIG__?.apiUrl) {
    return window.__FREQID_CONFIG__.apiUrl;
  }
  if (import.meta.env.VITE_BACKEND_URL) {
    return import.meta.env.VITE_BACKEND_URL;
  }
  if (typeof window !== "undefined" && window.location?.origin) {
    return window.location.origin;
  }
  return "http://localhost:8000";
}

// Track single-flight refresh promise to prevent duplicate refresh calls
let refreshPromise: Promise<string | null> | null = null;

export async function refreshAccessToken(): Promise<string | null> {
  if (refreshPromise) {
    return refreshPromise;
  }

  refreshPromise = (async () => {
    try {
      const baseUrl = getApiBaseUrl();
      const res = await fetch(`${baseUrl}/v1/admin/auth/refresh`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Request-ID": `ref-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`,
        },
        credentials: "include", // Send HttpOnly refresh cookie
      });

      if (!res.ok) {
        authStore.clearSession();
        return null;
      }

      const data = await res.json();
      const user: AdminUser = {
        admin_id: data.admin_id,
        username: data.username,
        role: data.role,
        permissions: data.permissions || [],
      };

      authStore.setSession(data.access_token, user);
      return data.access_token as string;
    } catch {
      authStore.clearSession();
      return null;
    } finally {
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

// Create base openapi-fetch client
export const api = createClient<paths>({
  baseUrl: getApiBaseUrl(),
  credentials: "include",
  fetch: (...args) => globalThis.fetch(...args),
});

// Intercept requests and responses via custom client wrapper
api.use({
  async onRequest({ request }) {
    // 1. Inject Bearer access token if present
    const token = authStore.getAccessToken();
    if (token && !request.headers.has("Authorization")) {
      request.headers.set("Authorization", `Bearer ${token}`);
    }

    // 2. Inject correlation request ID if not provided
    if (!request.headers.has("X-Request-ID")) {
      request.headers.set(
        "X-Request-ID",
        `req-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`
      );
    }

    return request;
  },

  async onResponse({ request, response }) {
    if (response.ok) {
      return response;
    }

    // Handle 401 Unauthorized
    if (response.status === 401) {
      const url = request.url;
      // Do not attempt refresh on login or refresh endpoints themselves
      if (url.includes("/v1/admin/auth/login") || url.includes("/v1/admin/auth/refresh")) {
        return response;
      }

      // Single-flight refresh attempt
      const newToken = await refreshAccessToken();
      if (newToken) {
        // Retry the original request with the new access token
        const headers = new Headers(request.headers);
        headers.set("Authorization", `Bearer ${newToken}`);
        const retryRequest = new Request(request.url, {
          method: request.method,
          headers,
          body: request.body,
          credentials: "include",
        });
        return fetch(retryRequest);
      }
    }

    // Handle 403 Forbidden
    if (response.status === 403) {
      toast.error("Permission Denied", {
        description: "Your administrative role lacks the required scope for this action.",
      });
    }

    // Handle 429 Too Many Requests
    if (response.status === 429) {
      const retryAfter = response.headers.get("Retry-After") || "60";
      toast.error("Rate Limit Exceeded", {
        description: `Too many requests. Please wait ${retryAfter} seconds before retrying.`,
      });
    }

    // Handle 503 Service Unavailable
    if (response.status === 503) {
      toast.error("Service Temporarily Unavailable", {
        description: "The server is currently busy or re-initializing. Please try again shortly.",
      });
    }

    return response;
  },
});

export async function parseApiError(response: Response): Promise<ApiError> {
  const status = response.status;
  try {
    const data = await response.json();
    if (data.error && typeof data.error === "object") {
      return new ApiError(status, {
        code: data.error.code || `HTTP_${status}`,
        message: data.error.message || response.statusText,
        request_id: data.error.request_id || response.headers.get("X-Request-ID") || undefined,
        retry_after: data.error.retry_after,
        details: data.error.details,
      });
    }
    if (data.detail) {
      return new ApiError(status, {
        code: `HTTP_${status}`,
        message: typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail),
        request_id: response.headers.get("X-Request-ID") || undefined,
      });
    }
    return new ApiError(status, {
      code: `HTTP_${status}`,
      message: data.message || response.statusText,
      request_id: response.headers.get("X-Request-ID") || undefined,
    });
  } catch {
    return new ApiError(status, {
      code: `HTTP_${status}`,
      message: response.statusText || `Request failed with status ${status}`,
      request_id: response.headers.get("X-Request-ID") || undefined,
    });
  }
}
