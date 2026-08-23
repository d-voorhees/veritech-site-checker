"use client";

import { Suspense, useEffect, useRef } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError } from "@/lib/api";
import { productConfig } from "@/lib/config";
import { useVerifyMagicLink } from "@/lib/use-auth";

function VerifyContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token");
  const verify = useVerifyMagicLink();
  const attempted = useRef(false);

  useEffect(() => {
    if (token && !attempted.current) {
      attempted.current = true;
      verify.mutate(token);
    }
  }, [token, verify]);

  let body: React.ReactNode;
  if (!token) {
    body = <p className="text-sm text-red-600">This link is missing its sign-in token.</p>;
  } else if (verify.isError) {
    body = (
      <p className="text-sm text-red-600">
        {verify.error instanceof ApiError ? String(verify.error.detail) : "This sign-in link is invalid or has expired."}
      </p>
    );
  } else {
    body = <p className="text-sm text-muted-foreground">Signing you in…</p>;
  }

  return (
    <>
      {body}
      {(verify.isError || !token) && (
        <Link href="/login" className="text-sm underline">
          Request a new sign-in link
        </Link>
      )}
    </>
  );
}

export default function VerifyPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <Card className="w-full max-w-sm border-0">
        <CardHeader className="gap-2 pb-5 pt-6">
          <div className="eyebrow text-primary">{productConfig.parentBrand}</div>
          <CardTitle className="text-xl font-bold tracking-tight text-foreground">
            {productConfig.productName}
          </CardTitle>
          <CardDescription>Verifying your sign-in link</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Suspense fallback={<p className="text-sm text-muted-foreground">Signing you in…</p>}>
            <VerifyContent />
          </Suspense>
        </CardContent>
      </Card>
    </div>
  );
}
