import Image from "next/image";
import { Installation } from "@/components/installation";
import { UsageGuide } from "@/components/usage-guide";
import { Wordmark } from "@/components/wordmark";

export default function Home() {
  return (
    <>
      <a
        href="#main"
        className="absolute -top-[100px] left-5 z-10 bg-accent p-3 text-surface focus:top-2.5"
      >
        Skip to content
      </a>
      <div className="mx-4 max-w-[1120px] border-x border-line max-[23.4375rem]:mx-2.5 md:mx-6 desktop:mx-auto">
        <header className="flex h-[72px] items-center justify-between border-b border-line px-[22px] max-[23.4375rem]:px-4 md:h-20 md:px-11">
          <Wordmark />
          <nav
            aria-label="Main navigation"
            className="flex items-center gap-[19px] font-mono text-[10px] max-[23.4375rem]:gap-3 md:gap-8 md:text-xs"
          >
            <a href="#how-to-use" className="hover:text-accent">
              How to use
            </a>
            <a
              href="https://github.com/madvillax/convo"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-accent"
            >
              GitHub{" "}
              <span aria-hidden="true" className="ml-[5px] text-muted">
                ↗
              </span>
            </a>
            <a
              href="#install"
              className="hidden bg-accent px-4 py-2.5 font-[650] text-surface hover:bg-[#ffbf33] md:inline-block"
            >
              Install{" "}
              <span aria-hidden="true" className="pl-4">
                ↓
              </span>
            </a>
          </nav>
        </header>
        <main id="main">
          <section
            aria-labelledby="hero-title"
            className="px-[22px] max-[23.4375rem]:px-4 md:px-11"
          >
            <div className="pt-[51px] pb-[35px] text-center md:pt-14 md:pb-[52px] desktop:pt-[68px] wide:pt-20">
              <p className="mb-6 font-mono text-[8px] tracking-[1px] text-muted max-[23.4375rem]:tracking-[.4px] md:mb-[25px] md:text-[10px] md:tracking-[1.4px]">
                <span
                  aria-hidden="true"
                  className="px-[5px] text-accent md:px-[9px]"
                >
                  [
                </span>{" "}
                OPEN SOURCE. TERMINAL NATIVE.{" "}
                <span
                  aria-hidden="true"
                  className="px-[5px] text-accent md:px-[9px]"
                >
                  ]
                </span>
              </p>
              <h1
                id="hero-title"
                className="text-[clamp(42px,8.8vw,64px)] leading-[1.02] font-normal tracking-[-2.5px] max-[23.4375rem]:text-[38px] max-[23.4375rem]:tracking-[-2px] md:text-[clamp(52px,6.5vw,82px)] md:tracking-[-4.6px]"
              >
                Your files.
                <br />
                <span className="text-accent">A conversation.</span>
              </h1>
              <p className="mt-5 mb-[30px] text-[13px] leading-[1.7] tracking-[-.2px] text-muted md:mt-[23px] md:text-base">
                Ask your files anything. Get answers with sources.
                <br className="max-[23.4375rem]:hidden" /> All from the terminal
                you already call home.
              </p>
              <Installation />
            </div>
            <figure className="relative border border-[#393933] before:absolute before:-top-2.5 before:-left-1.5 before:bg-surface before:font-mono before:text-[17px] before:leading-[17px] before:text-[#84847b] before:content-['+'] after:absolute after:-top-2.5 after:-right-1.5 after:bg-surface after:font-mono after:text-[17px] after:leading-[17px] after:text-[#84847b] after:content-['+']">
              <div className="flex items-center justify-between border-b border-line bg-raised p-3 font-mono text-[8px] leading-[1.7] text-muted md:px-[22px] md:py-[15px] md:text-[10px]">
                <span>
                  <span
                    aria-hidden="true"
                    className="mr-1.5 text-[11px] text-accent md:mr-[11px] md:text-[13px]"
                  >
                    &gt;_
                  </span>{" "}
                  A little less searching. A little more knowing.
                </span>
                <span className="hidden text-[#c1c1b8] md:inline">convo</span>
              </div>
              <div className="overflow-hidden bg-surface">
                <Image
                  src="/images/convo-chat.png"
                  alt="Convo terminal showing a question about a RAG pipeline, an answer with code, and a supporting source quotation from architecture.md."
                  width={1400}
                  height={1400}
                  sizes="(max-width: 767px) calc(100vw - 78px), (max-width: 1100px) calc(100vw - 136px), 1030px"
                  preload
                  className="-my-[8.8%] block h-auto w-full"
                />
              </div>
              <figcaption className="flex items-center justify-between gap-[18px] border-t border-line px-3 py-[13px] font-mono text-[8px] text-muted md:px-[22px] md:py-[17px] md:text-[10px]">
                <span>One file. Real context. Cited answers.</span>
                <a
                  href="#how-to-use"
                  className="hidden text-[#ecece6] hover:text-accent md:inline"
                >
                  Make yourself at home{" "}
                  <span aria-hidden="true" className="pl-[7px] text-accent">
                    ↓
                  </span>
                </a>
              </figcaption>
            </figure>
          </section>
          <UsageGuide />
        </main>
        <footer className="flex flex-wrap items-center justify-between gap-2.5 border-t border-line px-[22px] py-6 md:flex-nowrap md:gap-6 md:px-11 md:py-[27px]">
          <Wordmark footer />
          <p className="mr-auto text-[10px] text-muted md:text-[11px]">
            Good questions start here.
          </p>
          <a
            href="https://github.com/madvillax/convo/blob/main/LICENSE"
            target="_blank"
            rel="noopener noreferrer"
            className="mt-[5px] w-full font-mono text-[9px] text-muted hover:text-accent md:mt-0 md:w-auto"
          >
            Open source. MIT licensed.{" "}
            <span aria-hidden="true" className="pl-[5px] text-accent">
              ↗
            </span>
          </a>
        </footer>
      </div>
    </>
  );
}
