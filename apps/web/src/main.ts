// Vercel's Geist README recommends these self-hosted Fontsource families for
// non-Next projects. Load only the Latin weights this page uses.
import "@fontsource/geist-sans/latin-400.css";
import "@fontsource/geist-sans/latin-500.css";
import "@fontsource/geist-sans/latin-600.css";
import "@fontsource/geist-sans/latin-700.css";
import "@fontsource/geist-mono/latin-400.css";
import "@fontsource/geist-mono/latin-500.css";
import "@fontsource/geist-mono/latin-600.css";
import "@fontsource/geist-mono/latin-700.css";
import "./style.css";

const installCommands = {
  uv: "uv tool install convo-cli",
  curl: "curl -LsSf https://raw.githubusercontent.com/madvillax/convo/main/scripts/install.sh | sh",
};
let currentInstall: keyof typeof installCommands = "uv";
const announcement = document.querySelector<HTMLElement>("#announcement")!;
const installCode = document.querySelector<HTMLElement>("#install-code")!;
const installPanel = document.querySelector<HTMLElement>("#install-panel")!;
const installNote = document.querySelector<HTMLElement>("#install-note")!;

// Shared keyboard behavior keeps both tab sets usable without a pointer.
document.querySelectorAll<HTMLElement>('[role="tablist"]').forEach((tablist) => {
  const tabs = [...tablist.querySelectorAll<HTMLButtonElement>('[role="tab"]')];
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((item) => {
        const selected = item === tab;
        item.setAttribute("aria-selected", String(selected));
        item.tabIndex = selected ? 0 : -1;
        if (item.dataset.category) {
          document.getElementById(item.getAttribute("aria-controls")!)!.hidden = !selected;
        }
      });
      if (tab.dataset.method) {
        currentInstall = tab.dataset.method as keyof typeof installCommands;
        installCode.textContent = installCommands[currentInstall];
        installPanel.setAttribute("aria-labelledby", tab.id);
        installNote.replaceChildren();
        if (currentInstall === "uv") {
          installNote.append("Requires ");
          const uvLink = document.createElement("a");
          uvLink.href = "https://docs.astral.sh/uv/getting-started/installation/";
          uvLink.textContent = "uv ↗";
          uvLink.target = "_blank";
          uvLink.rel = "noopener noreferrer";
          installNote.append(uvLink, " and Docker or Podman for local storage.");
        } else {
          installNote.textContent =
            "Installs uv and Convo. Inspect the script first. Docker or Podman required.";
        }
      }
    });
    tab.addEventListener("keydown", (event) => {
      const index = tabs.indexOf(tab);
      let next: number;
      if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
      else if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = tabs.length - 1;
      else return;
      event.preventDefault();
      tabs[next]!.focus();
      tabs[next]!.click();
    });
  });
});

document.querySelectorAll<HTMLButtonElement>(".copy-button").forEach((button) => {
  button.addEventListener("click", async () => {
    const text =
      button.id === "copy-install"
        ? installCommands[currentInstall]
        : button.dataset.copy!.replaceAll("\\n", "\n");
    const originalLabel = button.getAttribute("aria-label")!;
    const label = button.querySelector<HTMLElement>(".copy-label");
    button.disabled = true;
    try {
      await navigator.clipboard.writeText(text);
      button.dataset.copied = "true";
      button.setAttribute("aria-label", "Copied to clipboard");
      if (label) label.textContent = "Copied";
      announcement.textContent = "Command copied to clipboard.";
    } catch {
      if (label) label.textContent = "Select text";
      button.setAttribute("aria-label", "Select and copy the command manually");
      announcement.textContent = "Clipboard unavailable. Select the command and copy it manually.";
      const code = button.parentElement!.querySelector("code")!;
      const range = document.createRange();
      range.selectNodeContents(code);
      window.getSelection()?.removeAllRanges();
      window.getSelection()?.addRange(range);
    }
    window.setTimeout(() => {
      delete button.dataset.copied;
      button.setAttribute("aria-label", originalLabel);
      if (label) label.textContent = "Copy";
      button.disabled = false;
    }, 2000);
  });
});
