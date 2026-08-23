/** @type {import('next').NextConfig} */
const nextConfig = {
  // Proxy /api/* → backend to avoid CORS issues
  // In dev: NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1 → backend at http://localhost:8000
  // In prod: via nginx reverse proxy
  async rewrites() {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';
    // Extract base URL (remove /api/v1 suffix)
    const backendBase = apiUrl.replace(/\/api\/v1\/?$/, '') || 'http://localhost:8000';
    
    return [
      {
        source: '/api/:path*',
        destination: `${backendBase}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
