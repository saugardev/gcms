import type { NextConfig } from "next";

const config: NextConfig = {
  poweredByHeader: false,
  async rewrites() {
    const origin = process.env.GCMS_API_URL ?? "http://127.0.0.1:8001";
    return [{ source: "/ws/analyses/:id", destination: `${origin}/v1/analyses/:id/events` }];
  },
};

export default config;
