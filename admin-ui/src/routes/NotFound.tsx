// Copyright 2026 FreqID Authors. Apache-2.0 License.
import React from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { ShieldQuestion } from "lucide-react";

export const NotFound: React.FC = () => {
  return (
    <div className="flex min-h-[70vh] flex-col items-center justify-center p-6 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-muted text-muted-foreground mb-4">
        <ShieldQuestion className="h-8 w-8" />
      </div>
      <h1 className="text-3xl font-bold tracking-tight text-foreground">404 - Page Not Found</h1>
      <p className="mt-2 text-sm text-muted-foreground max-w-sm">
        The requested administrative route does not exist or has been relocated.
      </p>
      <div className="mt-6">
        <Button asChild>
          <Link to="/dashboard">Return to Dashboard</Link>
        </Button>
      </div>
    </div>
  );
};
