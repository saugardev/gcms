"use client";

export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <main className="state-page">
      <h1>The workspace could not load</h1>
      <p>Your saved analyses are unchanged.</p>
      <button onClick={reset}>Try again</button>
    </main>
  );
}
