export function Wordmark({ footer = false }: { footer?: boolean }) {
  return (
    <a
      href="#"
      aria-label="Convo home"
      className={`inline-flex items-center font-mono font-[750] tracking-[-1.6px] ${footer ? "text-[21px]" : "text-2xl md:text-[27px]"}`}
    >
      {!footer ? (
        <span
          aria-hidden="true"
          className="relative mr-[9px] block h-5 w-[17px] border-[5px] border-r-0 border-accent after:absolute after:right-0 after:bottom-0 after:h-[5px] after:w-1.5 after:bg-accent md:mr-3 md:h-[22px] md:w-5"
        />
      ) : null}
      convo
      <span aria-hidden="true" className="text-accent">
        _
      </span>
    </a>
  );
}
