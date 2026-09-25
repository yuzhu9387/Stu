import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  distDir: process.env.NEXT_DIST_DIR || ".next",
  output: "standalone",
  reactStrictMode: true,
  devIndicators: false,
};

export default nextConfig;
