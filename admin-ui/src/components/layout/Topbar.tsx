// Copyright 2026 FreqID Authors. Apache-2.0 License.
import React from "react";
import { Link, useLocation } from "react-router-dom";
import { useSession } from "@/auth/AuthContext";
import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { User, LogOut, ChevronRight } from "lucide-react";

export const Topbar: React.FC = () => {
  const { user, logout } = useSession();
  const location = useLocation();

  // Simple breadcrumb generator from pathname
  const pathParts = location.pathname.split("/").filter(Boolean);

  const roleBadgeVariant = (role?: string) => {
    switch (role) {
      case "owner":
        return "destructive";
      case "admin":
        return "default";
      case "operator":
        return "secondary";
      case "auditor":
        return "outline";
      default:
        return "secondary";
    }
  };

  return (
    <header className="h-16 border-b bg-card px-6 flex items-center justify-between sticky top-0 z-30">
      {/* Breadcrumbs */}
      <nav aria-label="Breadcrumb" className="flex items-center space-x-2 text-sm text-muted-foreground">
        <Link to="/dashboard" className="hover:text-foreground transition-colors">
          Home
        </Link>
        {pathParts.map((part, index) => {
          const href = "/" + pathParts.slice(0, index + 1).join("/");
          const isLast = index === pathParts.length - 1;
          const label = part.charAt(0).toUpperCase() + part.slice(1).replace(/-/g, " ");

          return (
            <React.Fragment key={href}>
              <ChevronRight className="h-4 w-4 shrink-0 opacity-50" />
              {isLast ? (
                <span className="font-medium text-foreground">{label}</span>
              ) : (
                <Link to={href} className="hover:text-foreground transition-colors">
                  {label}
                </Link>
              )}
            </React.Fragment>
          );
        })}
      </nav>

      {/* Right Controls */}
      <div className="flex items-center gap-3">
        <ThemeToggle />

        {/* User Account Menu */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" className="flex items-center gap-2 pl-2 pr-3 h-9">
              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-primary font-semibold text-xs">
                {user?.username?.charAt(0).toUpperCase() || "A"}
              </div>
              <div className="flex flex-col text-left">
                <span className="text-xs font-medium leading-none text-foreground">
                  {user?.username}
                </span>
                <span className="text-[10px] text-muted-foreground leading-none mt-1">
                  {user?.role}
                </span>
              </div>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuLabel className="font-normal">
              <div className="flex flex-col space-y-1">
                <p className="text-sm font-medium leading-none">{user?.username}</p>
                <div className="pt-1">
                  <Badge variant={roleBadgeVariant(user?.role)} className="capitalize text-[10px] px-1.5 py-0">
                    {user?.role} role
                  </Badge>
                </div>
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild>
              <Link to="/account" className="flex items-center gap-2 cursor-pointer">
                <User className="h-4 w-4" />
                <span>My Account</span>
              </Link>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={() => logout()}
              className="text-destructive focus:bg-destructive/10 focus:text-destructive flex items-center gap-2 cursor-pointer"
            >
              <LogOut className="h-4 w-4" />
              <span>Log out</span>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
};
