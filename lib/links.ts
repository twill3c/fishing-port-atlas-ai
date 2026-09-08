/**
 * フリート共通フッタのリンク先。
 *
 * 規約は 5 項目・この並び・下部固定:
 *   MIT License © 2026 坂田哲朗 ・ GitHub ・ <歩き方> ・ <設計図> ・ App Menu
 *
 * 「歩き方」「設計図」は本来は解説アーティファクトを指す。まだ発行していないので、
 * **暫定でアプリ内の解説ページを指している**(死んだリンクを出さないため)。
 * 発行したらここだけを差し替える。
 */
export const FLEET_LINKS = {
  license: "https://github.com/twill3c/fishing-port-atlas-ai/blob/main/LICENSE",
  github: "https://github.com/twill3c/fishing-port-atlas-ai",
  guide: { href: "/about/", label: "漁港アトラスの歩き方" },
  design: { href: "/methodology/", label: "漁港アトラス 設計図" },
  appMenu: "https://app-menu.vercel.app/",
} as const;
