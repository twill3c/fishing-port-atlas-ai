import type { Metadata } from "next";

import { SiteFooter } from "@/components/SiteFooter";

import "./globals.css";
import "maplibre-gl/dist/maplibre-gl.css";

export const metadata: Metadata = {
  title: "Fishing Port Atlas AI — 日本の漁港を公開データで眺める",
  description:
    "全国 2,768 の指定漁港を、水産庁「漁港一覧」と国土数値情報から再現し、種別・所在・座標の由来つきで地図に並べる。",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ja">
      <body>
        {children}
        <SiteFooter />
      </body>
    </html>
  );
}
