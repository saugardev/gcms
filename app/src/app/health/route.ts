import { apiOrigin } from "@/lib/session";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const response = await fetch(`${apiOrigin}/health`, {
      cache: "no-store",
      signal: AbortSignal.timeout(5_000),
    });
    if (!response.ok) throw new Error("API unavailable");
    const health = await response.json();
    if (health.status !== "ok" || health.storage !== "postgresql") throw new Error("Storage unavailable");
    return Response.json({ ...health, app: "mafer-workspace", revision: process.env.DEPLOYMENT_VERSION ?? "local" });
  } catch {
    return Response.json({ status: "unavailable" }, { status: 503 });
  }
}
