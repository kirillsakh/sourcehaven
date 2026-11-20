import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // Caddy fronts the site and the API streams server-sent events directly, never through Next.js.
  compress: false,
  poweredByHeader: false,
};

export default nextConfig;
