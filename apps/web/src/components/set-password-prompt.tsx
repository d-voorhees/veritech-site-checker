"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { ApiError } from "@/lib/api";
import { useMe, useSetPassword } from "@/lib/use-auth";

const MIN_PASSWORD_LENGTH = 10;

function clientPasswordError(password: string): string | null {
  if (password.length < MIN_PASSWORD_LENGTH) return `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
  if (!/[A-Za-z]/.test(password) || !/[0-9]/.test(password)) {
    return "Password must include at least one letter and one number.";
  }
  return null;
}

export function SetPasswordPrompt() {
  const { data: me } = useMe();
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const setPasswordMutation = useSetPassword();

  if (!me || me.has_password) return null;

  const errorMessage =
    formError ??
    (setPasswordMutation.isError
      ? setPasswordMutation.error instanceof ApiError
        ? String(setPasswordMutation.error.detail)
        : "Could not set your password."
      : null);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 px-4 backdrop-blur-sm">
      <Card className="w-full max-w-sm">
        <CardHeader className="gap-2 pb-5 pt-6">
          <CardTitle className="text-xl font-bold tracking-tight text-foreground">Set a password</CardTitle>
          <CardDescription>
            You signed in with an email link. Set a password now so you can sign back in without waiting on an
            email next time.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              setFormError(null);

              if (password !== confirmPassword) {
                setFormError("Passwords don't match.");
                return;
              }
              const clientError = clientPasswordError(password);
              if (clientError) {
                setFormError(clientError);
                return;
              }

              setPasswordMutation.mutate(password);
            }}
          >
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="new-password">Password</Label>
              <Input
                id="new-password"
                type="password"
                required
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="confirm-password">Confirm password</Label>
              <Input
                id="confirm-password"
                type="password"
                required
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
              />
            </div>
            {errorMessage && <p className="text-sm text-red-600">{errorMessage}</p>}
            <Button type="submit" disabled={setPasswordMutation.isPending} className="w-full">
              {setPasswordMutation.isPending ? "Saving…" : "Set password"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
