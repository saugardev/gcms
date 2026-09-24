import { test } from "node:test";
import assert from "node:assert/strict";
import { safeReturnTo } from "./auth-path.ts";

test("login return paths cannot escape the app or target auth/API endpoints", () => {
  for (const target of ["//evil.test", "/\\evil.test", "/\n/evil.test", "https://evil.test", "/api/auth/logout", "/login", "/register?x=1", ["/", "//evil.test"], null, {}]) {
    assert.equal(safeReturnTo(target), "/");
  }
  assert.equal(safeReturnTo("/?analysis=abc&peak=component-0001"), "/?analysis=abc&peak=component-0001");
});
