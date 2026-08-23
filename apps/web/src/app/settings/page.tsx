"use client";

import { AppShell } from "@/components/app-shell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { productConfig } from "@/lib/config";
import { useRequireAuth } from "@/lib/use-auth";

export default function SettingsPage() {
  const { data: me } = useRequireAuth();

  return (
    <AppShell>
      <h1 className="text-xl font-semibold tracking-tight">Settings</h1>

      <Card className="mt-6 max-w-lg">
        <CardHeader>
          <CardTitle>Profile</CardTitle>
          <CardDescription>Account details for this {productConfig.productName} workspace.</CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-1 gap-3 text-sm">
            <div>
              <dt className="text-xs uppercase tracking-wide text-muted-foreground">Name</dt>
              <dd className="mt-0.5">{me?.full_name || "—"}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-muted-foreground">Email</dt>
              <dd className="mt-0.5">{me?.email}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-muted-foreground">Role</dt>
              <dd className="mt-0.5 capitalize">{me?.role}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-muted-foreground">Organization</dt>
              <dd className="mt-0.5">{me?.organization_name}</dd>
            </div>
          </dl>
        </CardContent>
      </Card>
    </AppShell>
  );
}
