"use client";
import Link from "next/link";
import { useState } from "react";
import { safeReturnTo } from "@/lib/auth-path";

export function AuthForm({ register = false, returnTo = "/" }: { register?: boolean; returnTo?: string }) {
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true); setError("");
    const form = new FormData(event.currentTarget);
    try {
      const response = await fetch(`/api/auth/${register ? "register" : "login"}`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ email: form.get("email"), password: form.get("password"), ...(register ? { name: form.get("name") } : {}) }),
      });
      if (!response.ok) throw new Error((await response.json()).error?.message ?? "Could not sign in.");
      location.assign(safeReturnTo(returnTo));
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not sign in.");
      setPending(false);
    }
  }
  return <main className="auth-page">
    <div className="auth-brand"><img src="/mafer-logo.svg" alt="Mafer" width={104} height={21} /></div>
    <section className="auth-card">
      <h1>{register ? "Create your account" : "Sign in to Mafer"}</h1>
      <p>Review chromatograms and save candidate decisions with your team.</p>
      <form onSubmit={submit}>
        {register && <label>Name<input name="name" autoComplete="name" required minLength={2} maxLength={100} /></label>}
        <label>Email<input name="email" type="email" autoComplete="email" required maxLength={254} /></label>
        <label>Password<input name="password" type="password" autoComplete={register ? "new-password" : "current-password"} required minLength={8} maxLength={1024} /></label>
        {error && <p role="alert" className="auth-error">{error}</p>}
        <button disabled={pending}>{pending ? "Please wait…" : register ? "Create account" : "Sign in"}</button>
      </form>
      {register && <p className="auth-policy">All registered users can view the stored analyses and edit shared candidate decisions.</p>}
      <Link href={`${register ? "/login" : "/register"}?return_to=${encodeURIComponent(safeReturnTo(returnTo))}`}>
        {register ? "Already have an account? Sign in" : "Create an account"}
      </Link>
    </section>
  </main>;
}
