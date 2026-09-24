import { NextRequest, NextResponse } from "next/server";
import { apiOrigin, appOrigin, SESSION_COOKIE } from "@/lib/session";

const analysisPath = /^analyses(?:\/[a-f0-9]{64}(?:\/(?:spectra|scans|ions|components\/component-\d{4}))?)?$/;
function error(message: string, status: number) {
  return NextResponse.json({ error: { message } }, { status, headers: { "cache-control": "no-store" } });
}
async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path: segments } = await context.params;
  const path = segments.join("/");
  const auth = request.method === "POST" && ["auth/login", "auth/register"].includes(path);
  const logout = request.method === "POST" && path === "auth/logout";
  const read = request.method === "GET" && (analysisPath.test(path) || path === "me");
  if (!auth && !logout && !read) return error("Endpoint not found.", 404);
  if (request.method !== "GET" && request.headers.get("origin") !== appOrigin) {
    return error("Request origin is not allowed.", 403);
  }
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (!auth && !token) return error("Sign in again to continue.", 401);
  const headers = new Headers({ accept: "application/json" });
  if (!auth) headers.set("authorization", `Session ${token}`);
  let body: string | undefined;
  if (auth) {
    if (request.headers.get("content-type")?.split(";")[0] !== "application/json") return error("Send JSON.", 415);
    // Bound the streamed body as well as Content-Length before buffering credentials.
    const reader = request.body?.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    if (reader) {
      while (true) {
        const next = await reader.read();
        if (next.done) break;
        size += next.value.byteLength;
        if (size > 16 * 1024) { await reader.cancel(); return error("Request is too large.", 413); }
        chunks.push(next.value);
      }
    }
    body = Buffer.concat(chunks).toString("utf8");
    headers.set("content-type", "application/json");
  }
  try {
    const response = await fetch(`${apiOrigin}/v1/${segments.map(encodeURIComponent).join("/")}${request.nextUrl.search}`, {
      method: request.method, headers, body, cache: "no-store", signal: AbortSignal.timeout(15_000), redirect: "error",
    });
    const responseHeaders = new Headers({ "cache-control": "no-store" });
    responseHeaders.set("content-type", response.headers.get("content-type") ?? "application/json");
    const timing = response.headers.get("server-timing");
    if (timing) responseHeaders.set("server-timing", timing);
    if (auth && response.ok) {
      const result = await response.json();
      const output = NextResponse.json({ user: result.user }, { status: response.status, headers: responseHeaders });
      output.cookies.set(SESSION_COOKIE, result.session_token, {
        httpOnly: true, secure: process.env.NODE_ENV === "production", sameSite: "lax", path: "/",
        expires: new Date(result.expires_at * 1000),
      });
      return output;
    }
    const output = new NextResponse(response.body, { status: response.status, headers: responseHeaders });
    if ((!auth && response.status === 401) || (logout && response.ok)) output.cookies.delete(SESSION_COOKIE);
    return output;
  } catch {
    return error("The server is unavailable. Please try again.", 503);
  }
}
export const GET = proxy;
export const POST = proxy;
