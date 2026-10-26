import type { NextConfig } from "next";

// NEXT_OUTPUT=export builds a static site into out/ (copied to ../web by `npm run build:web`)
// that the backend serves directly – used by the one-click start scripts.
const staticExport = process.env.NEXT_OUTPUT === "export";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: staticExport ? "export" : "standalone",
  poweredByHeader: false,
};

export default nextConfig;
