// Copyright 2026 FreqID Authors. Apache-2.0 License.
import React from "react";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { CheckCircle2, Clock, PauseCircle, XCircle, AlertCircle } from "lucide-react";
import { formatRelativeTime, formatExactTimestamp } from "@/lib/formatters";

interface DeviceStatusBadgeProps {
  state: string;
  lastSeen?: string | null;
}

export const DeviceStatusBadge: React.FC<DeviceStatusBadgeProps> = ({ state, lastSeen }) => {
  const isStale = lastSeen
    ? Date.now() - new Date(lastSeen).getTime() > 5 * 60 * 1000 // > 5 minutes
    : true;

  const getBadgeConfig = () => {
    switch (state) {
      case "active":
        if (isStale) {
          return {
            variant: "warning" as const,
            icon: AlertCircle,
            label: "Offline (Stale)",
          };
        }
        return {
          variant: "success" as const,
          icon: CheckCircle2,
          label: "Active",
        };
      case "pending":
        return {
          variant: "warning" as const,
          icon: Clock,
          label: "Pending",
        };
      case "suspended":
        return {
          variant: "warning" as const,
          icon: PauseCircle,
          label: "Suspended",
        };
      case "revoked":
        return {
          variant: "destructive" as const,
          icon: XCircle,
          label: "Revoked",
        };
      default:
        return {
          variant: "outline" as const,
          icon: AlertCircle,
          label: state,
        };
    }
  };

  const { variant, icon: Icon, label } = getBadgeConfig();

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className="inline-flex items-center gap-1.5 cursor-help">
            <Badge variant={variant} className="flex items-center gap-1 font-medium capitalize text-xs">
              <Icon className="h-3 w-3" />
              <span>{label}</span>
            </Badge>
            {lastSeen && (
              <span className="text-[11px] text-muted-foreground hidden sm:inline">
                ({formatRelativeTime(lastSeen)})
              </span>
            )}
          </div>
        </TooltipTrigger>
        <TooltipContent>
          <p className="text-xs">
            Status: <span className="font-semibold capitalize">{state}</span>
          </p>
          <p className="text-xs text-muted-foreground">
            Last seen: {formatExactTimestamp(lastSeen)}
          </p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};
