import type { NextConfig } from 'next'

/**
 * Gateway target for /api/* rewrites.
 *
 * Order of precedence:
 *   1. GATEWAY_UPSTREAM (server-side runtime, e.g. "http://gateway:5000" inside Docker)
 *   2. NEXT_PUBLIC_GATEWAY_URL (build-time, baked in)
 *   3. Fallback "http://localhost:5000" for local dev
 */
const GATEWAY =
  process.env.GATEWAY_UPSTREAM ||
  process.env.NEXT_PUBLIC_GATEWAY_URL ||
  'http://localhost:5000'

const nextConfig: NextConfig = {
  // Proxy /api/* (incl. SSE) to the Caddy gateway → same-origin in browser.
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${GATEWAY}/api/:path*`,
      },
    ]
  },

  // Standalone output → small Docker image with built-in Node server,
  // no need to ship full node_modules.
  output: 'standalone',

  reactStrictMode: true,
  images: {
    dangerouslyAllowSVG: true,
  },
}

export default nextConfig
