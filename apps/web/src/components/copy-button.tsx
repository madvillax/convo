"use client";

import { useEffect, useRef, useState } from "react";

export function CopyButton({
  text,
  label,
  compact = false,
}: {
  text: string;
  label: string;
  compact?: boolean;
}) {
  const [status, setStatus] = useState<"idle" | "copied" | "error">("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const button = useRef<HTMLButtonElement>(null);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setStatus("copied");
    } catch {
      setStatus("error");
      const code = button.current?.parentElement?.querySelector("code");
      if (code) {
        const range = document.createRange();
        range.selectNodeContents(code);
        const selection = window.getSelection();
        selection?.removeAllRanges();
        selection?.addRange(range);
      }
    }
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setStatus("idle"), 2000);
  }

  return (
    <>
      <button
        ref={button}
        type="button"
        aria-label={
          status === "copied"
            ? "Copied to clipboard"
            : status === "error"
              ? "Select and copy the command manually"
              : label
        }
        disabled={status === "copied"}
        data-copied={status === "copied" ? "true" : undefined}
        onClick={copy}
        className={`copy-button inline-flex min-h-8 shrink-0 items-center justify-center gap-[9px] bg-transparent p-2 font-mono text-[11px] text-muted hover:text-accent data-copied:text-accent ${compact ? "absolute top-[13px] right-2.5 min-w-8" : "min-w-8 md:min-w-[69px]"}`}
      >
        <span
          aria-hidden="true"
          className={
            status === "copied"
              ? "ml-[3px] inline-block h-1.5 w-[11px] -rotate-45 border-b border-l border-current"
              : "relative ml-[3px] inline-block h-3 w-[11px] border border-current before:absolute before:-top-1 before:-left-1 before:h-[9px] before:w-2 before:border-t before:border-l before:border-current"
          }
        />
        {!compact ? (
          <span className="hidden md:inline">
            {status === "copied"
              ? "Copied"
              : status === "error"
                ? "Select text"
                : "Copy"}
          </span>
        ) : null}
      </button>
      <span className="sr-only" role="status" aria-live="polite">
        {status === "copied"
          ? "Command copied to clipboard."
          : status === "error"
            ? "Clipboard unavailable. Select the command and copy it manually."
            : ""}
      </span>
    </>
  );
}
