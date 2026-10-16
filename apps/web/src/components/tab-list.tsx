"use client";

import { useRef, type ReactNode } from "react";

type Option<Value extends string> = {
  value: Value;
  label: string;
  panelId: string;
};

export function TabList<Value extends string>({
  label,
  options,
  value,
  onChange,
  trailing,
  small = false,
}: {
  label: string;
  options: readonly Option<Value>[];
  value: Value;
  onChange: (value: Value) => void;
  trailing?: ReactNode;
  small?: boolean;
}) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);

  return (
    <div
      role="tablist"
      aria-label={label}
      className="flex items-center gap-[22px] border-b border-line"
    >
      {options.map((option, index) => (
        <button
          key={option.value}
          ref={(element) => {
            buttons.current[index] = element;
          }}
          id={`tab-${option.value}`}
          type="button"
          role="tab"
          aria-selected={value === option.value}
          aria-controls={option.panelId}
          tabIndex={value === option.value ? 0 : -1}
          className={`relative bg-transparent px-[3px] py-2.5 font-mono text-muted hover:text-accent aria-selected:text-accent aria-selected:after:absolute aria-selected:after:-bottom-px aria-selected:after:inset-x-0 aria-selected:after:h-0.5 aria-selected:after:bg-accent ${small ? "pb-[13px] text-[10px]" : "text-xs"}`}
          onClick={() => onChange(option.value)}
          onKeyDown={(event) => {
            let next: number;
            if (event.key === "ArrowRight") next = (index + 1) % options.length;
            else if (event.key === "ArrowLeft")
              next = (index - 1 + options.length) % options.length;
            else if (event.key === "Home") next = 0;
            else if (event.key === "End") next = options.length - 1;
            else return;
            event.preventDefault();
            onChange(options[next].value);
            buttons.current[next]?.focus();
          }}
        >
          {option.label}
        </button>
      ))}
      {trailing}
    </div>
  );
}
