// Copyright 2026 FreqID Authors. Apache-2.0 License.
import React, { useState, useEffect } from "react";
import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";
import { WifiOff } from "lucide-react";

export const AppShell: React.FC = () => {
  const [isOnline, setIsOnline] = useState(navigator.onLine);

  useEffect(() => {
    const handleOnline = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        {!isOnline && (
          <div
            role="status"
            aria-live="polite"
            className="bg-destructive text-destructive-foreground px-4 py-2 text-xs flex items-center justify-center gap-2 font-medium"
          >
            <WifiOff className="h-4 w-4" />
            <span>Network disconnected. Changes will not be saved until connection is restored.</span>
          </div>
        )}
        <Topbar />
        <main className="flex-1 p-6 md:p-8 max-w-7xl w-full mx-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
};
