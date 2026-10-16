"use client";

import { useState } from "react";
import { TabList } from "./tab-list";

const groups = {
  everyday: [
    ["/login", "Connect your ChatGPT account"],
    ["/file", "Choose and index a file"],
    ["/models", "Search and choose a model"],
    ["/thinking", "Choose the thinking effort"],
    ["/help", "See all commands and keys"],
    ["/quit", "Close Convo"],
  ],
  session: [
    ["/sessions", "Find and resume saved chats"],
    ["/new", "New chat, same selected file"],
    ["/clear", "Same as /new; keeps old chats"],
    ["/reset", "New chat without a file"],
    ["/sessions <uuid>", "Resume a chat directly by ID"],
  ],
  terminal: [
    ["Ctrl+O", "Open the file picker"],
    ["Ctrl+T / Shift+Tab", "Cycle supported thinking levels"],
    ["F2", "Pick a thinking level directly"],
    ["PageUp / PageDown", "Scroll the conversation"],
    ["Esc", "Cancel file preparation"],
    ["Ctrl+C", "Exit Convo"],
  ],
} as const;
type Category = keyof typeof groups;
const options = [
  { value: "everyday", label: "Everyday", panelId: "commands-everyday" },
  { value: "session", label: "Sessions", panelId: "commands-session" },
  { value: "terminal", label: "Terminal", panelId: "commands-terminal" },
] as const;

export function CommandReference() {
  const [category, setCategory] = useState<Category>("everyday");

  return (
    <aside
      aria-label="Convo command reference"
      className="min-w-0 self-start border border-line bg-[#0f0f0f] px-[22px] pt-[27px] md:px-[25px]"
    >
      <h3 className="text-[22px] leading-[1.35] font-medium tracking-[-.7px]">
        A few commands.
        <br />A lot less friction.
      </h3>
      <p className="mt-[13px] mb-[21px] text-[11px] leading-[1.7] text-muted">
        Type <code className="font-mono text-accent">/</code> in Convo to see
        suggestions.
      </p>
      <TabList
        label="Command category"
        options={options}
        value={category}
        onChange={setCategory}
        small
      />
      {options.map(({ value, panelId }) => (
        <dl
          key={value}
          id={panelId}
          role="tabpanel"
          aria-labelledby={`tab-${value}`}
          tabIndex={0}
          hidden={value !== category}
          className="mt-2 pb-2 md:min-h-[282px] md:pb-0"
        >
          {groups[value].map(([command, description]) => (
            <div
              key={command}
              className="grid grid-cols-[1fr_1.4fr] items-baseline gap-[13px] py-3 md:block md:py-2.5"
            >
              <dt className="font-mono text-[10px] text-accent wrap-anywhere md:text-xs">
                {command}
              </dt>
              <dd className="text-[10px] leading-[1.6] text-muted md:mt-1 md:text-[11px]">
                {description}
              </dd>
            </div>
          ))}
        </dl>
      ))}
      <p className="mt-[15px] mb-6 text-[10px] leading-[1.9] text-muted">
        <span aria-hidden="true" className="mr-[5px] text-accent">
          ↳
        </span>{" "}
        In the command menu:{" "}
        <kbd className="border border-line px-1 py-px font-mono text-[9px] text-[#ddddce]">
          ↑
        </kbd>{" "}
        <kbd className="border border-line px-1 py-px font-mono text-[9px] text-[#ddddce]">
          ↓
        </kbd>{" "}
        to navigate,{" "}
        <kbd className="border border-line px-1 py-px font-mono text-[9px] text-[#ddddce]">
          Tab
        </kbd>{" "}
        to complete.
      </p>
      <details className="group border-t border-line">
        <summary className="flex list-none items-center justify-between py-[19px] text-[11px]">
          What files can I bring?{" "}
          <span
            aria-hidden="true"
            className="font-mono text-lg text-accent transition-transform duration-160 group-open:rotate-45"
          >
            +
          </span>
        </summary>
        <p className="mb-[18px] text-[11px] leading-[1.9] text-muted">
          TXT, Markdown, PDF, DOCX, CSV, JSON, Python, RST, and log files. Up to
          10 MB per file, with a limit of 500,000 extracted characters and 2,000
          chunks.
        </p>
        <p className="mb-[18px] text-[11px] leading-[1.9] text-muted">
          Files are indexed locally. Relevant passages go to your connected
          ChatGPT account to generate an answer.
        </p>
      </details>
    </aside>
  );
}
