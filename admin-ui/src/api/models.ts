// Copyright 2026 FreqID Authors. Apache-2.0 License.
import { components } from "./v1";

export type DeviceSummary = components["schemas"]["DeviceSummary"] & {
  ip_address?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type DeviceDetail = components["schemas"]["DeviceDetail"] & {
  ip_address?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type SystemStatusResponse = components["schemas"]["SystemStatusResponse"];

export interface UserSummary {
  id: string;
  external_id: string;
  is_active: boolean;
  model_version?: string;
  sample_count?: number;
  quality_score?: number;
  created_at?: string;
  updated_at?: string;
}

export interface AuditEventItem {
  id: string;
  event_time: string;
  event_type: string;
  principal_type: string;
  principal_id?: string;
  user_id?: string;
  device_id?: string;
  admin_id?: string;
  decision: string;
  request_id?: string;
  client_ip?: string;
  prev_hash?: string;
  current_hash?: string;
  coarse_score_bucket?: string;
  metadata?: Record<string, unknown>;
}

export interface AdminAccountItem {
  id: string;
  username: string;
  role: "owner" | "admin" | "operator" | "auditor";
  is_active: boolean;
  failed_logins: number;
  locked_until?: string | null;
  created_at?: string;
  updated_at?: string;
}
