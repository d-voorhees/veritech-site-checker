import { fileURLToPath } from "node:url";

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Standalone output ships a minimal server.js + only the node_modules it
  // actually needs — the Fly production image runs this instead of
  // `next start` against a full node_modules tree (see Dockerfile).
  output: "standalone",
  // Pin the workspace root explicitly — without it Next.js's root inference
  // can pick a parent directory that happens to have its own lockfile
  // (e.g. a sibling project on the same machine), which throws off build
  // tracing.
  outputFileTracingRoot: fileURLToPath(new URL(".", import.meta.url)),
  reactStrictMode: true,
  async rewrites() {
    // On Fly, the API process runs alongside Next.js in the same Machine
    // (see scripts/entrypoint.sh) at API_INTERNAL_URL, and this rewrite
    // proxies /api/* and /health to it so the browser only ever talks to
    // one origin — no CORS, no separate reverse proxy needed. In local dev
    // this is a no-op (NEXT_PUBLIC_API_BASE_URL is used directly instead).
    const apiInternalUrl = process.env.API_INTERNAL_URL;
    if (!apiInternalUrl) return [];
    return [
      { source: "/api/:path*", destination: `${apiInternalUrl}/api/:path*` },
      { source: "/health", destination: `${apiInternalUrl}/health` },
    ];
  },
};

export default nextConfig;
