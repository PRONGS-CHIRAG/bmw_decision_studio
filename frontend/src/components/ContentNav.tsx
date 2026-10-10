import { useEffect, useState } from "react";

/** bmw.de in-page content navigation: sticky tab bar, active underline, CTA on the right. */
export default function ContentNav({
  sections,
  cta,
  onCta,
}: {
  sections: { id: string; label: string }[];
  cta: string;
  onCta: () => void;
}) {
  const [active, setActive] = useState(sections[0]?.id);
  useEffect(() => {
    const els = sections.map((s) => document.getElementById(s.id)).filter(Boolean) as HTMLElement[];
    const io = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setActive(visible[0].target.id);
      },
      { rootMargin: "-90px 0px -60% 0px" },
    );
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [sections]);
  return (
    <nav className="contentnav" aria-label="Sections of the evaluation">
      <div className="wrap contentnav__inner">
        <div className="contentnav__tabs">
          {sections.map((s) => (
            <a key={s.id} href={`#${s.id}`} className="contentnav__tab" aria-current={active === s.id ? "true" : undefined}>
              {s.label}
            </a>
          ))}
        </div>
        <button className="btn contentnav__cta" onClick={onCta}>
          {cta}
        </button>
      </div>
    </nav>
  );
}
