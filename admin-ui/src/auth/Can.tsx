// Copyright 2026 FreqID Authors. Apache-2.0 License.
import React from "react";
import { Permission } from "./permissions";
import { useCan } from "./useCan";

export interface CanProps {
  permission: Permission;
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

export const Can: React.FC<CanProps> = ({ permission, children, fallback = null }) => {
  const allowed = useCan(permission);
  if (!allowed) {
    return <>{fallback}</>;
  }
  return <>{children}</>;
};
