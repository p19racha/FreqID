// Copyright 2026 FreqID Authors. Apache-2.0 License.
import React from "react";
import { NavLink } from "react-router-dom";
import { useSession } from "@/auth/AuthContext";
import { PERMISSIONS } from "@/auth/permissions";
import { cn } from "@/lib/utils";
import {
  LayoutDashboard,
  Camera,
  Users,
  FileText,
  UserCog,
  Settings,
  Activity,
  User,
  Shield,
} from "lucide-react";

interface NavItem {
  title: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  permission?: (typeof PERMISSIONS)[keyof typeof PERMISSIONS];
}

const navItems: NavItem[] = [
  {
    title: "Dashboard",
    href: "/dashboard",
    icon: LayoutDashboard,
  },
  {
    title: "Devices",
    href: "/devices",
    icon: Camera,
    permission: PERMISSIONS.DEVICE_LIST,
  },
  {
    title: "Users",
    href: "/users",
    icon: Users,
    permission: PERMISSIONS.USER_LIST,
  },
  {
    title: "Audit Log",
    href: "/audit",
    icon: FileText,
    permission: PERMISSIONS.AUDIT_READ,
  },
  {
    title: "Admin Accounts",
    href: "/admin/accounts",
    icon: UserCog,
    permission: PERMISSIONS.ADMIN_CREATE, // Owner only
  },
  {
    title: "Settings",
    href: "/admin/settings",
    icon: Settings,
    permission: PERMISSIONS.SETTINGS_UPDATE, // Owner only
  },
  {
    title: "System Status",
    href: "/system/status",
    icon: Activity,
    permission: PERMISSIONS.SYSTEM_STATUS,
  },
  {
    title: "My Account",
    href: "/account",
    icon: User,
  },
];

export const Sidebar: React.FC = () => {
  const { can, user } = useSession();

  const filteredItems = navItems.filter((item) => {
    if (!item.permission) return true;
    return can(item.permission);
  });

  return (
    <aside className="w-64 border-r bg-card flex flex-col h-screen sticky top-0">
      {/* Brand Header */}
      <div className="h-16 flex items-center px-6 border-b gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground font-bold shadow-sm">
          <Shield className="h-5 w-5" />
        </div>
        <div>
          <span className="font-semibold tracking-tight text-foreground block text-sm">
            FreqID Admin
          </span>
          <span className="text-xs text-muted-foreground block">
            {user?.role ? user.role.toUpperCase() : "PORTAL"}
          </span>
        </div>
      </div>

      {/* Navigation Links */}
      <nav className="flex-1 px-4 py-4 space-y-1 overflow-y-auto">
        {filteredItems.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.href}
              to={item.href}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-md transition-colors",
                  isActive
                    ? "bg-primary text-primary-foreground shadow-sm"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )
              }
            >
              <Icon className="h-4 w-4 shrink-0" />
              <span>{item.title}</span>
            </NavLink>
          );
        })}
      </nav>

      {/* Footer Info */}
      <div className="p-4 border-t text-xs text-muted-foreground">
        <div className="flex items-center justify-between">
          <span>FreqID Core v0.1.0</span>
          <span className="h-2 w-2 rounded-full bg-emerald-500" title="Online" />
        </div>
      </div>
    </aside>
  );
};
