/**
 * フリート共通フッタのリンク先。
 *
 * 規約は 5 項目・この並び・下部固定:
 *   MIT License © 2026 坂田哲朗 ・ GitHub ・ <歩き方> ・ <設計図> ・ App Menu
 *
 * 「歩き方」「設計図」は解説アーティファクトを指す(2026-09-09 発行)。
 * アプリ内の /about/ と /methodology/ は同じ話をアプリの文脈で書いたもので、
 * 画面上部のナビゲーションから辿れる。フッタからはアーティファクトへ出す。
 */
export const FLEET_LINKS = {
  license: "https://github.com/twill3c/fishing-port-atlas-ai/blob/main/LICENSE",
  github: "https://github.com/twill3c/fishing-port-atlas-ai",
  guide: {
    href: "https://claude.ai/code/artifact/2fbf47f0-b289-4b7a-9ae8-2e28d2bc7e83",
    label: "漁港アトラスの歩き方",
  },
  design: {
    href: "https://claude.ai/code/artifact/a8b9ed76-079e-40eb-9898-3a4a1e717976",
    label: "漁港アトラス 設計図",
  },
  appMenu: "https://app-menu.vercel.app/",
} as const;
