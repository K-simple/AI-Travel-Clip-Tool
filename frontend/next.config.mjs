const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    const apiBase = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000';
    return [
      {
        source: '/api/:path*',
        destination: `${apiBase.replace(/\/$/, '')}/api/:path*`,
      },
      {
        source: '/storage/:path*',
        destination: `${apiBase.replace(/\/$/, '')}/storage/:path*`,
      },
    ];
  },
};

export default nextConfig;
