// Copyright 2026 FreqID Authors. Apache-2.0 License.
import React from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useSession } from "./AuthContext";
import { Permission } from "./permissions";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent } from "@/components/ui/card";
import { ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ProtectedRouteProps {
  children?: React.ReactNode;
  requiredPermission?: Permission;
}

export function sanitizeReturnTo(path: string): string {
  if (!path || typeof path !== "string") return "/dashboard";
  // Must start with single / and not // (protocol-relative url) or javascript:
  if (path.startsWith("/") && !path.startsWith("//") && !path.includes("://")) {
    return path;
  }
  return "/dashboard";
}

export const ProtectedRoute: React.FC<ProtectedRouteProps> = ({
  children,
  requiredPermission,
}) => {
  const { isAuthenticated, isBootstrapping, can } = useSession();
  const location = useLocation();

  // 1. Silent bootstrap check: do not flash login screen while session is being verified
  if (isBootstrapping) {
    return (
      <div className="flex h-screen w-full items-center justify-center p-6 bg-background">
        <div className="flex flex-col items-center space-y-4 max-w-sm w-full">
          <div className="h-10 w-10 animate-spin rounded-full border-4 border-primary border-t-transparent" />
          <p className="text-sm text-muted-foreground animate-pulse">
            Verifying administrative credentials...
          </p>
          <Skeleton className="h-4 w-48" />
        </div>
      </div>
    );
  }

  // 2. Unauthenticated: redirect to login with safe returnTo parameter
  if (!isAuthenticated) {
    const rawPath = location.pathname + location.search;
    const safePath = sanitizeReturnTo(rawPath);
    return <Navigate to={`/login?returnTo=${encodeURIComponent(safePath)}`} replace />;
  }

  // 3. Permission check
  if (requiredPermission && !can(requiredPermission)) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center p-6">
        <Card className="max-w-md w-full border-destructive/20 bg-destructive/5">
          <CardContent className="pt-6 text-center space-y-4">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10 text-destructive">
              <ShieldAlert className="h-6 w-6" />
            </div>
            <h2 className="text-lg font-semibold tracking-tight text-foreground">
              Access Restricted
            </h2>
            <p className="text-sm text-muted-foreground">
              Your administrative role does not have the{" "}
              <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-foreground">
                {requiredPermission}
              </code>{" "}
              permission required to view this area.
            </p>
            <div className="pt-2">
              <Button variant="outline" onClick={() => window.history.back()}>
                Go Back
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return children ? <>{children}</> : null;
};
