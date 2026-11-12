/** @type {import('next').NextConfig} */
// NEXT_DIST_DIR lets a long-running `next dev` keep its own output folder, so a
// `next build` in the same checkout can't overwrite the files the dev server is serving.
const nextConfig = { reactStrictMode: true, distDir: process.env.NEXT_DIST_DIR || ".next" };
export default nextConfig;
