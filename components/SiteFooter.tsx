import { FLEET_LINKS } from "@/lib/links";

/**
 * フリート共通フッタ(5 項目・この並び・下部固定)。
 *
 * 「・」は文字として置く —— CSS の `::before` で描くと `innerText` に出ず、
 * 検品器から見えなくなる。
 * `© 2026 坂田哲朗` はリンク文言の外の地の文にする(規約の一部)。
 */
export function SiteFooter() {
  return (
    <nav className="fleet" aria-label="サイト情報">
      <a href={FLEET_LINKS.license} target="_blank" rel="noreferrer">
        MIT License
      </a>
      <span> © 2026 坂田哲朗</span>
      <span className="fsep">・</span>
      <a href={FLEET_LINKS.github} target="_blank" rel="noreferrer">
        GitHub
      </a>
      <span className="fsep">・</span>
      <a href={FLEET_LINKS.guide.href}>{FLEET_LINKS.guide.label}</a>
      <span className="fsep">・</span>
      <a href={FLEET_LINKS.design.href}>{FLEET_LINKS.design.label}</a>
      <span className="fsep">・</span>
      <a href={FLEET_LINKS.appMenu} target="_blank" rel="noreferrer">
        App Menu
      </a>
    </nav>
  );
}
