"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { FileSearch, LayoutDashboard, ListChecks, LogOut, User } from "lucide-react";

import { SetPasswordPrompt } from "@/components/set-password-prompt";
import { Button } from "@/components/ui/button";
import { productConfig } from "@/lib/config";
import { useLogout, useMe } from "@/lib/use-auth";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/scans", label: "Scans", icon: ListChecks },
  { href: "/scans/new", label: "New Scan", icon: FileSearch },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const logout = useLogout();
  const { data: me } = useMe();

  return (
    <div className="min-h-screen">
      <SetPasswordPrompt />
      <header className="border-b-2 border-primary bg-background">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <div className="flex items-center gap-8">
            <Link href="/dashboard">
              <div className="text-base font-bold tracking-tight text-foreground">{productConfig.productName}</div>
              <div className="eyebrow mb-0 text-primary">{productConfig.parentBrand}</div>
            </Link>
            <nav className="hidden items-center gap-6 md:flex">
              {NAV_ITEMS.map((item) => {
                const active = pathname === item.href || (item.href !== "/" && pathname?.startsWith(item.href));
                const Icon = item.icon;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={cn(
                      "flex items-center gap-1.5 border-b-2 py-1 text-sm font-medium transition-colors",
                      active
                        ? "border-primary text-foreground"
                        : "border-transparent text-muted-foreground hover:text-foreground"
                    )}
                  >
                    <Icon className="h-3.5 w-3.5" />
                    {item.label}
                  </Link>
                );
              })}
            </nav>
          </div>
          <div className="flex items-center gap-3">
            {me && (
              <span
                className="hidden text-xs font-medium text-muted-foreground sm:inline"
                title={`Scans reset on a rolling 24-hour window. Need more? Contact danielle@veritechdiligence.com.`}
              >
                {me.scans_used_today} / {me.scan_daily_limit} scans today
              </span>
            )}
            <Link
              href="/settings"
              title="Profile"
              aria-label="Profile"
              className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <User className="h-4 w-4" />
            </Link>
            <Button
              variant="ghost"
              size="sm"
              title="Sign out"
              aria-label="Sign out"
              className="h-8 w-8 px-0"
              onClick={() => logout.mutate()}
            >
              <LogOut className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
    </div>
  );
}
