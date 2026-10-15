// Copyright 2026 FreqID Authors. Apache-2.0 License.
import { Permission } from "./permissions";
import { useSession } from "./AuthContext";

export function useCan(permission: Permission): boolean {
  const { can } = useSession();
  return can(permission);
}
