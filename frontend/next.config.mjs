/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The production image runs `next start` from a standalone bundle, which
  // keeps the container small and its startup fast.
  output: "standalone",
  poweredByHeader: false,
  eslint: {
    // Linting runs as its own step (`npm run lint`), so a lint warning does not
    // fail the container build.
    ignoreDuringBuilds: true,
  },
};

export default nextConfig;
