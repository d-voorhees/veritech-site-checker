// Lightweight readiness check for the Next.js process itself. Distinct from
// /health, which next.config.mjs rewrites to the API process.
export async function GET() {
  return Response.json({ status: "ok" });
}
