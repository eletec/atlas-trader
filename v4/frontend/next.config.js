/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/api/v4/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_URL ?? "http://atlas-v4-api:8000"}/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
