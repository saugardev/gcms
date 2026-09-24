import "server-only";
import { cookies } from "next/headers";

// Browser-session flow adapted from saas-template; see THIRD_PARTY_NOTICES.md.
export const SESSION_COOKIE = "mafer_session";
export const apiOrigin = process.env.GCMS_API_URL ?? "http://127.0.0.1:8001";
export const appOrigin = new URL(process.env.APP_ORIGIN ?? "http://127.0.0.1:3000").origin;
export type SessionUser = { id: string; name: string; email: string };

export async function currentUser(): Promise<SessionUser | null> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) return null;
  const response = await fetch(`${apiOrigin}/v1/me`, {
    headers: { authorization: `Session ${token}` },
    cache: "no-store",
    signal: AbortSignal.timeout(10_000),
  });
  if (response.status === 401) return null;
  if (!response.ok) throw new Error("Sign-in is temporarily unavailable. Please try again.");
  return (await response.json()).user;
}
