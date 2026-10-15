// Copyright 2026 FreqID Authors. Apache-2.0 License.

export interface ApiErrorDetail {
  code: string;
  message: string;
  request_id?: string;
  retry_after?: number;
  details?: Record<string, unknown>;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId?: string;
  readonly retryAfter?: number;
  readonly details?: Record<string, unknown>;

  constructor(status: number, detail: ApiErrorDetail) {
    super(detail.message || `API request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.code = detail.code || `HTTP_${status}`;
    this.requestId = detail.request_id;
    this.retryAfter = detail.retry_after;
    this.details = detail.details;
  }
}
