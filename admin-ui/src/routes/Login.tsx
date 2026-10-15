// Copyright 2026 FreqID Authors. Apache-2.0 License.
import React, { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useSession } from "@/auth/AuthContext";
import { sanitizeReturnTo } from "@/auth/ProtectedRoute";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Shield, Lock, AlertCircle, Copy, Check } from "lucide-react";
import { ApiError } from "@/api/errors";

export const Login: React.FC = () => {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [showTotpField, setShowTotpField] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [errorRequestId, setErrorRequestId] = useState<string | null>(null);
  const [lockoutSeconds, setLockoutSeconds] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);

  const { login, isAuthenticated } = useSession();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const returnTo = sanitizeReturnTo(searchParams.get("returnTo") || "/dashboard");

  // Redirect if already authenticated
  useEffect(() => {
    if (isAuthenticated) {
      navigate(returnTo, { replace: true });
    }
  }, [isAuthenticated, navigate, returnTo]);

  // Handle lockout countdown timer
  useEffect(() => {
    if (lockoutSeconds === null || lockoutSeconds <= 0) return;
    const interval = setInterval(() => {
      setLockoutSeconds((prev) => {
        if (prev === null || prev <= 1) {
          clearInterval(interval);
          setErrorMessage(null);
          return null;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, [lockoutSeconds]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setErrorMessage(null);
    setErrorRequestId(null);

    try {
      await login(username, password, showTotpField ? totpCode : undefined);
      navigate(returnTo, { replace: true });
    } catch (err: unknown) {
      // Clear sensitive password field immediately on failure
      setPassword("");
      setTotpCode("");

      if (err instanceof ApiError) {
        setErrorRequestId(err.requestId || null);

        // Check if TOTP is required
        if (err.message && err.message.toLowerCase().includes("totp")) {
          setShowTotpField(true);
          setErrorMessage("Please enter your 6-digit two-factor authentication (TOTP) code.");
          return;
        }

        // Check for lockout
        if (err.status === 423 || err.code === "ACCOUNT_LOCKED" || err.retryAfter) {
          const secs = err.retryAfter || 900;
          setLockoutSeconds(secs);
          setErrorMessage(`Account or IP locked due to repeated failed logins. Please retry in ${secs} seconds.`);
          return;
        }

        // Generic error message for anti-enumeration
        setErrorMessage(err.message || "Invalid administrative username or password.");
      } else {
        setErrorMessage("Unable to connect to the authentication service. Please check your network connection.");
      }
    } finally {
      setIsLoading(false);
    }
  };

  const copyErrorDetails = () => {
    if (!errorRequestId) return;
    navigator.clipboard.writeText(`Error: ${errorMessage} (Request ID: ${errorRequestId})`);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="flex min-h-screen w-full items-center justify-center p-4 bg-muted/30">
      <div className="w-full max-w-md space-y-6">
        <div className="flex flex-col items-center text-center space-y-2">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-md">
            <Shield className="h-6 w-6" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">FreqID Admin</h1>
          <p className="text-sm text-muted-foreground">
            Privacy-Preserving Biometric Fleet Management
          </p>
        </div>

        <Card className="border-border shadow-lg">
          <CardHeader className="space-y-1">
            <CardTitle className="text-xl">Sign in</CardTitle>
            <CardDescription>
              Enter your credentials to access the administrative portal
            </CardDescription>
          </CardHeader>

          <form onSubmit={handleSubmit}>
            <CardContent className="space-y-4">
              {errorMessage && (
                <div
                  className="rounded-lg border border-destructive/20 bg-destructive/10 p-3 text-sm text-destructive flex flex-col space-y-2"
                  role="alert"
                >
                  <div className="flex items-start space-x-2">
                    <AlertCircle className="h-5 w-5 shrink-0 mt-0.5" />
                    <span className="flex-1">{errorMessage}</span>
                  </div>
                  {errorRequestId && (
                    <div className="flex items-center justify-between text-xs text-muted-foreground pt-1 border-t border-destructive/10">
                      <span className="font-mono">Req ID: {errorRequestId}</span>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-6 px-2 text-xs"
                        onClick={copyErrorDetails}
                      >
                        {copied ? <Check className="h-3 w-3 mr-1 text-emerald-500" /> : <Copy className="h-3 w-3 mr-1" />}
                        {copied ? "Copied" : "Copy details"}
                      </Button>
                    </div>
                  )}
                </div>
              )}

              <div className="space-y-2">
                <Label htmlFor="username">Username</Label>
                <Input
                  id="username"
                  name="username"
                  type="text"
                  required
                  autoComplete="username"
                  placeholder="admin"
                  disabled={isLoading || (lockoutSeconds !== null && lockoutSeconds > 0)}
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  name="password"
                  type="password"
                  required
                  autoComplete="current-password"
                  placeholder="••••••••••••"
                  disabled={isLoading || (lockoutSeconds !== null && lockoutSeconds > 0)}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>

              {showTotpField && (
                <div className="space-y-2 pt-2 border-t border-border">
                  <Label htmlFor="totp">Two-Factor Code (TOTP)</Label>
                  <Input
                    id="totp"
                    name="totp"
                    type="text"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    pattern="[0-9]*"
                    maxLength={6}
                    placeholder="123456"
                    autoFocus
                    required
                    disabled={isLoading}
                    value={totpCode}
                    onChange={(e) => setTotpCode(e.target.value.trim())}
                  />
                  <p className="text-xs text-muted-foreground">
                    Enter the code from your authenticator application
                  </p>
                </div>
              )}
            </CardContent>

            <CardFooter className="flex flex-col space-y-4">
              <Button
                type="submit"
                className="w-full"
                disabled={isLoading || (lockoutSeconds !== null && lockoutSeconds > 0)}
              >
                {isLoading ? (
                  <span className="flex items-center space-x-2">
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-primary-foreground border-t-transparent" />
                    <span>Signing in...</span>
                  </span>
                ) : lockoutSeconds !== null && lockoutSeconds > 0 ? (
                  `Locked out (${lockoutSeconds}s)`
                ) : (
                  <span className="flex items-center space-x-2">
                    <Lock className="h-4 w-4" />
                    <span>{showTotpField ? "Verify & Sign In" : "Sign In"}</span>
                  </span>
                )}
              </Button>

              <div className="text-center text-xs text-muted-foreground">
                Protected by FreqID End-to-End Cryptographic Access Control
              </div>
            </CardFooter>
          </form>
        </Card>
      </div>
    </div>
  );
};
