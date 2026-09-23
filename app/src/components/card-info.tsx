"use client";

import { useId, type ReactNode } from "react";

export function CardInfo({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <>
      <button
        type="button"
        className="card-info"
        aria-label={`About ${title}`}
        aria-describedby={id}
        popoverTarget={id}
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 20 20"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          aria-hidden="true"
        >
          <circle cx="10" cy="10" r="7.5" />
          <path d="M10 9v5" />
          <circle cx="10" cy="6.5" r=".75" fill="currentColor" stroke="none" />
        </svg>
      </button>
      <div id={id} className="card-tooltip" role="tooltip" popover="auto">
        {children}
      </div>
    </>
  );
}
