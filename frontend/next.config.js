/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    // In local development the Next.js dev server runs on port 3000 and the
    // FastAPI backend runs on port 8000.  This rewrite proxies all /api/*
    // requests from the browser through the Next.js server to the FastAPI,
    // eliminating the cross-origin request that would otherwise require CORS.
    //
    // In production (Vercel) this function returns an empty array; routing is
    // handled by vercel.json which directs /api/* to the Python serverless
    // function at the same origin.
    if (process.env.NODE_ENV !== "production") {
      return [
        {
          source: "/api/:path*",
          destination: "http://localhost:8000/api/:path*",
        },
      ];
    }
    return [];
  },
};

module.exports = nextConfig;
