// Copyright 2026 FreqID Authors. Apache-2.0 License.
import React, { useState } from "react";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
  AlertDialogAction,
} from "@/components/ui/alert-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Trash2 } from "lucide-react";

interface DeleteUserDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  user: { id: string; external_id: string } | null;
  onConfirm: (userId: string) => Promise<void>;
  isLoading?: boolean;
}

export const DeleteUserDialog: React.FC<DeleteUserDialogProps> = ({
  open,
  onOpenChange,
  user,
  onConfirm,
  isLoading = false,
}) => {
  const [confirmText, setConfirmText] = useState("");

  if (!user) return null;

  const isConfirmed = confirmText.trim() === user.external_id;

  const handleConfirm = async (e: React.MouseEvent) => {
    e.preventDefault();
    if (!isConfirmed) return;
    await onConfirm(user.id);
    setConfirmText("");
    onOpenChange(false);
  };

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent className="border-destructive/30 max-w-md">
        <AlertDialogHeader>
          <div className="flex items-center gap-2 text-destructive">
            <Trash2 className="h-5 w-5 shrink-0" />
            <AlertDialogTitle>Permanently Delete User Identity?</AlertDialogTitle>
          </div>
          <AlertDialogDescription className="space-y-3 pt-2 text-left">
            <p>
              You are about to delete enrolled user{" "}
              <strong className="text-foreground font-mono">{user.external_id}</strong> (GDPR Article 17 Right to Erasure).
            </p>
            <div className="rounded-md bg-destructive/10 p-3 text-xs text-destructive space-y-1.5">
              <p>
                <strong>What will be deleted:</strong>
              </p>
              <ul className="list-disc list-inside space-y-0.5">
                <li>User identity record and metadata.</li>
                <li>All enrolled 512-D encrypted biometric templates.</li>
              </ul>
              <p className="pt-1">
                <strong>What will remain:</strong> Historical audit log entries remain intact for compliance,
                anonymized with <code className="font-mono">user_id = NULL</code>.
              </p>
            </div>
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className="space-y-2 py-2">
          <Label htmlFor="confirm-user-id" className="text-xs">
            Type <strong className="font-mono text-destructive">{user.external_id}</strong> to confirm:
          </Label>
          <Input
            id="confirm-user-id"
            placeholder={user.external_id}
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            className="font-mono text-sm"
            autoFocus
          />
        </div>

        <AlertDialogFooter>
          <AlertDialogCancel onClick={() => setConfirmText("")}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            onClick={handleConfirm}
            disabled={!isConfirmed || isLoading}
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
          >
            {isLoading ? "Deleting..." : "Delete Identity Permanently"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
};
