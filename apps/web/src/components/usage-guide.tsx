import { CopyButton } from "./copy-button";
import { CommandReference } from "./command-reference";

const stepClass =
  "relative grid grid-cols-[28px_1fr] gap-[13px] pb-[37px] last:pb-0 md:gap-[17px] [&:not(:last-child)]:before:absolute [&:not(:last-child)]:before:top-[29px] [&:not(:last-child)]:before:bottom-[9px] [&:not(:last-child)]:before:left-[13px] [&:not(:last-child)]:before:w-px [&:not(:last-child)]:before:bg-line";
const numberClass =
  "flex h-[27px] items-center justify-center border border-[#4b3818] font-mono text-[10px] text-accent";
const titleClass =
  "mt-[3px] mb-[11px] text-base font-[540] tracking-[-.35px] md:text-[17px]";
const bodyClass =
  "text-xs leading-[1.8] text-muted md:text-[13px] [&_code]:font-mono [&_code]:text-[11px] [&_code]:text-[#e3e1d4] [&_code]:wrap-anywhere";
const noteClass =
  "mt-[13px] text-[11px] leading-[1.8] text-muted [&_code]:font-mono [&_code]:text-[#e3e1d4] [&_code]:wrap-anywhere";

export function UsageGuide() {
  return (
    <section
      id="how-to-use"
      aria-labelledby="usage-title"
      className="px-[22px] pt-[60px] pb-[45px] max-[23.4375rem]:px-4 md:px-11 md:pt-[94px] md:pb-[76px]"
    >
      <div className="pb-[30px] md:pb-[42px]">
        <h2
          id="usage-title"
          className="max-w-[310px] text-[31px] leading-[1.15] font-[520] tracking-[-1.3px] md:max-w-none md:text-[clamp(30px,3.3vw,41px)] md:tracking-[-1.7px]"
        >
          From directory to dialogue<span className="text-accent">.</span>
        </h2>
        <p className="mt-3.5 text-xs leading-[1.7] text-muted md:text-sm">
          Open your terminal. Bring a file. Start a convo.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-9 md:grid-cols-[1.25fr_1fr] md:gap-[30px] desktop:gap-14">
        <ol>
          <li className={stepClass}>
            <span aria-hidden="true" className={numberClass}>
              01
            </span>
            <div>
              <h3 className={titleClass}>Meet Convo in your directory</h3>
              <p className={bodyClass}>
                Move into the folder with your files, then launch Convo.
              </p>
              <div className="relative mt-[18px] border border-line bg-raised px-[13px] py-4 md:px-[18px]">
                <code className="font-mono text-xs leading-6">
                  <span
                    className="pr-3 text-accent select-none"
                    aria-hidden="true"
                  >
                    $
                  </span>{" "}
                  cd ~/Documents
                  <br />
                  <span
                    className="pr-3 text-accent select-none"
                    aria-hidden="true"
                  >
                    $
                  </span>{" "}
                  convo
                </code>
                <CopyButton
                  text={"cd ~/Documents\nconvo"}
                  label="Copy launch commands"
                  compact
                />
              </div>
              <p className={noteClass}>
                Or browse another folder with{" "}
                <code>convo --directory ~/Documents</code>. First launch
                prepares your local database.
              </p>
            </div>
          </li>
          <li className={stepClass}>
            <span aria-hidden="true" className={numberClass}>
              02
            </span>
            <div>
              <h3 className={titleClass}>Connect. Pick a file.</h3>
              <p className={bodyClass}>
                Use <code>/login</code> to connect your ChatGPT account in the
                browser. Then use <code>/file</code> to select and index a file.
              </p>
              <div className="mt-[17px] flex items-center gap-4 font-mono text-xs text-accent">
                <code>/login</code>
                <span aria-hidden="true" className="text-[#72726a]">
                  →
                </span>
                <code>/models</code>
                <span aria-hidden="true" className="text-[#72726a]">
                  →
                </span>
                <code>/file</code>
              </div>
              <p className={noteClass}>
                Choose your model with <code>/models</code>. The first file
                downloads the local embedding and reranking models.
              </p>
            </div>
          </li>
          <li className={stepClass}>
            <span aria-hidden="true" className={numberClass}>
              03
            </span>
            <div>
              <h3 className={titleClass}>Ask away. Follow the sources.</h3>
              <p className={bodyClass}>
                Type a question and press Enter. Read the answer alongside
                quotations from your selected file.
              </p>
              <div className="mt-[17px] border-l-2 border-accent bg-raised px-3.5 py-3 font-mono text-[11px] leading-[1.7]">
                <span aria-hidden="true" className="pr-[9px] text-accent">
                  ›
                </span>{" "}
                What are the key ideas in this document?
              </div>
              <p className={noteClass}>
                Conversations save automatically. Pick up where you left off
                with <code>/sessions</code>.
              </p>
            </div>
          </li>
        </ol>
        <CommandReference />
      </div>
    </section>
  );
}
