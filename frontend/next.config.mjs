const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  async rewrites() {
    const apiBase = (process.env.NEXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000')
      .replace(/\/$/, '')
      .replace('://localhost', '://127.0.0.1');
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
