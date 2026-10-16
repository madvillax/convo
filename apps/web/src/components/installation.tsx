"use client";

import { useState } from "react";
import { CopyButton } from "./copy-button";
import { TabList } from "./tab-list";

const commands = {
  uv: "uv tool install convo-cli",
  curl: "curl -LsSf https://raw.githubusercontent.com/madvillax/convo/main/scripts/install.sh | sh",
};
type Method = keyof typeof commands;
const options = [
  { value: "uv", label: "uv", panelId: "install-panel" },
  { value: "curl", label: "curl", panelId: "install-panel" },
] as const;

export function Installation() {
  const [method, setMethod] = useState<Method>("uv");

  return (
    <div
      id="install"
      className="mx-auto w-full max-w-[566px] scroll-mt-[35px] text-left"
    >
      <TabList
        label="Installation method"
        options={options}
        value={method}
        onChange={setMethod}
        trailing={
          <span className="ml-auto font-mono text-[8px] text-muted md:text-[10px]">
            macOS / Linux
          </span>
        }
      />
      <div
        id="install-panel"
        role="tabpanel"
        aria-labelledby={`tab-${method}`}
        tabIndex={0}
        className="flex min-h-[66px] items-center gap-3 border border-t-0 border-line bg-raised px-3 py-3.5 md:gap-[15px] md:px-[18px] md:py-[19px]"
      >
        <span aria-hidden="true" className="font-mono text-accent select-none">
          $
        </span>
        <code className="min-w-0 flex-1 overflow-x-auto font-mono text-[11px] leading-[1.8] whitespace-nowrap [scrollbar-width:thin] md:text-[13px]">
          {commands[method]}
        </code>
        <CopyButton
          key={method}
          text={commands[method]}
          label="Copy installation command"
        />
      </div>
      <p className="mt-3 min-h-[31px] font-mono text-[9px] leading-[1.7] text-muted md:min-h-[17px] md:text-[10px]">
        {method === "uv" ? (
          <>
            Requires{" "}
            <a
              href="https://docs.astral.sh/uv/getting-started/installation/"
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-3 hover:text-accent"
            >
              uv ↗
            </a>{" "}
            and Docker or Podman for local storage.
          </>
        ) : (
          "Installs uv and Convo. Inspect the script first. Docker or Podman required."
        )}
      </p>
    </div>
  );
}
