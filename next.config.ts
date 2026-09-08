import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  // 静的書き出し。Vercel では Python も学習も走らせない(SPEC N-03 / AC-014)。
  output: "export",
  images: { unoptimized: true },
  trailingSlash: true,
};

export default config;
