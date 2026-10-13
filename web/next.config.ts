import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Fully static: `next build` writes out/, served as plain files (no server, no API routes).
  output: "export",
  images: { unoptimized: true },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
