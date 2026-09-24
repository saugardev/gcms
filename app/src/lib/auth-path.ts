export function safeReturnTo(value: unknown): string {
  return typeof value === "string" && value.startsWith("/") && !value.startsWith("//") && !/[\\\x00-\x20\x7f]/.test(value)
    && !/^\/(?:login|register|api|ws)(?:[/?#]|$)/.test(value) ? value : "/";
}
