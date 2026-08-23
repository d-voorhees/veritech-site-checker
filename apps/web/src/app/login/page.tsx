"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { ApiError } from "@/lib/api";
import { productConfig } from "@/lib/config";
import { gtmPush } from "@/lib/gtm";
import { useLogin, useRequestMagicLink } from "@/lib/use-auth";

function SessionExpiredBanner() {
  const searchParams = useSearchParams();
  if (searchParams.get("session") !== "expired") return null;

  return (
    <div className="mb-4 border border-border bg-muted px-3 py-2 text-sm text-foreground">
      You have been logged out.
    </div>
  );
}

function MagicLinkForm({ sent, onSent }: { sent: boolean; onSent: () => void }) {
  const [email, setEmail] = useState("");
  const requestLink = useRequestMagicLink();

  if (sent) {
    return (
      <p className="text-sm text-muted-foreground">
        If that email is valid, a sign-in link is on its way. Check your inbox — the link expires in 20 minutes.
      </p>
    );
  }

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        requestLink.mutate(email, {
          onSuccess: () => {
            gtmPush({ event: "lead_submitted" });
            onSent();
          },
        });
      }}
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="email">Email</Label>
        <Input
          id="email"
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </div>
      {requestLink.isError && (
        <p className="text-sm text-red-600">
          {requestLink.error instanceof ApiError ? String(requestLink.error.detail) : "Could not send the sign-in link."}
        </p>
      )}
      <Button type="submit" disabled={requestLink.isPending} className="w-full">
        {requestLink.isPending ? "Sending…" : "Send sign-in link"}
      </Button>
    </form>
  );
}

function PasswordForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const login = useLogin();

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        login.mutate({ email, password });
      }}
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="email">Email</Label>
        <Input
          id="email"
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="password">Password</Label>
        <Input
          id="password"
          type="password"
          required
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </div>
      {login.isError && (
        <p className="text-sm text-red-600">
          {login.error instanceof ApiError ? String(login.error.detail) : "Sign-in failed."}
        </p>
      )}
      <Button type="submit" disabled={login.isPending} className="w-full">
        {login.isPending ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}

export default function LoginPage() {
  const [usePassword, setUsePassword] = useState(false);
  const [magicLinkSent, setMagicLinkSent] = useState(false);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="gap-2 border-b-0 pb-5 pt-6">
          <div className="eyebrow text-primary">{productConfig.parentBrand}</div>
          <CardTitle className="text-xl font-bold tracking-tight text-foreground">
            {productConfig.productName}
          </CardTitle>
          {!magicLinkSent && (
            <CardDescription>
              {usePassword ? "Sign in with your account." : "Enter your email and we'll send you a sign-in link."}
            </CardDescription>
          )}
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <Suspense fallback={null}>
            <SessionExpiredBanner />
          </Suspense>
          {usePassword ? (
            <PasswordForm />
          ) : (
            <MagicLinkForm sent={magicLinkSent} onSent={() => setMagicLinkSent(true)} />
          )}
          {(usePassword || !magicLinkSent) && (
            <button
              type="button"
              className="text-left text-sm text-muted-foreground underline"
              onClick={() => setUsePassword((v) => !v)}
            >
              {usePassword ? "Use a sign-in link instead" : "Sign in with a password instead"}
            </button>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
