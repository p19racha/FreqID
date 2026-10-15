// Copyright 2026 FreqID Authors. Apache-2.0 License.
import React, { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Copy, Check, ShieldCheck, FileText } from "lucide-react";
import { formatExactTimestamp } from "@/lib/formatters";

interface AuditEvent {
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

interface AuditDetailDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  event: AuditEvent | null;
}

export const AuditDetailDrawer: React.FC<AuditDetailDrawerProps> = ({
  open,
  onOpenChange,
  event,
}) => {
  const [copiedReqId, setCopiedReqId] = useState(false);
  const [copiedHash, setCopiedHash] = useState(false);

  if (!event) return null;

  const copyText = (text: string, type: "req" | "hash") => {
    navigator.clipboard.writeText(text);
    if (type === "req") {
      setCopiedReqId(true);
      setTimeout(() => setCopiedReqId(false), 2000);
    } else {
      setCopiedHash(true);
      setTimeout(() => setCopiedHash(false), 2000);
    }
  };

  const isPositiveDecision =
    event.decision === "authenticated" || event.decision === "verified" || event.decision === "allowed";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-primary" />
            <DialogTitle>Audit Event Details</DialogTitle>
          </div>
          <DialogDescription>
            Cryptographically sealed operational audit event record
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2 text-xs">
          {/* Top Status Banner */}
          <div className="flex items-center justify-between p-3 rounded-lg border bg-muted/40">
            <div>
              <span className="text-muted-foreground block">Event Classification</span>
              <span className="font-semibold text-sm text-foreground capitalize">
                {event.event_type.replace(/_/g, " ")}
              </span>
            </div>
            <Badge variant={isPositiveDecision ? "success" : "destructive"} className="capitalize">
              {event.decision}
            </Badge>
          </div>

          {/* Key-Value Details */}
          <div className="space-y-2.5 rounded-lg border p-3">
            <div className="flex justify-between py-1 border-b">
              <span className="text-muted-foreground">Timestamp</span>
              <span className="font-mono text-foreground">{formatExactTimestamp(event.event_time)}</span>
            </div>

            <div className="flex justify-between py-1 border-b">
              <span className="text-muted-foreground">Principal Type</span>
              <span className="font-semibold capitalize">{event.principal_type}</span>
            </div>

            {event.device_id && (
              <div className="flex justify-between py-1 border-b">
                <span className="text-muted-foreground">Device ID</span>
                <span className="font-mono text-foreground">{event.device_id}</span>
              </div>
            )}

            {event.user_id && (
              <div className="flex justify-between py-1 border-b">
                <span className="text-muted-foreground">Claimed Identity</span>
                <span className="font-mono text-foreground">{event.user_id}</span>
              </div>
            )}

            {event.admin_id && (
              <div className="flex justify-between py-1 border-b">
                <span className="text-muted-foreground">Admin ID</span>
                <span className="font-mono text-foreground">{event.admin_id}</span>
              </div>
            )}

            {event.coarse_score_bucket && (
              <div className="flex justify-between py-1 border-b">
                <span className="text-muted-foreground">Cosine Similarity Bucket</span>
                <Badge variant="outline" className="capitalize text-[10px]">
                  {event.coarse_score_bucket}
                </Badge>
              </div>
            )}

            {event.client_ip && (
              <div className="flex justify-between py-1 border-b">
                <span className="text-muted-foreground">Client Network Origin</span>
                <span className="font-mono">{event.client_ip}</span>
              </div>
            )}

            <div className="py-1">
              <div className="flex items-center justify-between text-muted-foreground mb-1">
                <span>Correlation Request ID</span>
                {event.request_id && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-5 px-1.5 text-[10px]"
                    onClick={() => copyText(event.request_id || "", "req")}
                  >
                    {copiedReqId ? <Check className="h-3 w-3 text-emerald-500 mr-1" /> : <Copy className="h-3 w-3 mr-1" />}
                    {copiedReqId ? "Copied" : "Copy"}
                  </Button>
                )}
              </div>
              <div className="p-2 rounded bg-muted/60 font-mono text-[11px] truncate select-all">
                {event.request_id || event.id}
              </div>
            </div>
          </div>

          {/* Tamper-Evident SHA-256 Hash Chaining Status */}
          <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3 space-y-2">
            <div className="flex items-center gap-1.5 text-emerald-700 dark:text-emerald-400 font-semibold">
              <ShieldCheck className="h-4 w-4" />
              <span>Tamper-Evident Hash Chain</span>
            </div>
            <p className="text-[11px] text-muted-foreground">
              Each record is cryptographically linked to its predecessor using SHA-256 running hash chaining.
            </p>
            {event.current_hash && (
              <div className="pt-1">
                <div className="flex items-center justify-between text-[10px] text-muted-foreground mb-0.5">
                  <span>Record Hash:</span>
                  <button
                    onClick={() => copyText(event.current_hash || "", "hash")}
                    className="text-primary hover:underline flex items-center gap-0.5"
                  >
                    {copiedHash ? <Check className="h-2.5 w-2.5 text-emerald-500" /> : <Copy className="h-2.5 w-2.5" />}
                    {copiedHash ? "Copied" : "Copy hash"}
                  </button>
                </div>
                <div className="font-mono text-[10px] bg-background p-1.5 rounded border truncate select-all">
                  {event.current_hash}
                </div>
              </div>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};
