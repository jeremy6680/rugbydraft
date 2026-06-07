import createNextIntlPlugin from "next-intl/plugin";

/**
 * next-intl plugin — points to our request config file.
 * This tells next-intl where to find the server-side configuration
 * (locale resolution + messages loading).
 */
const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

/** @type {import('next').NextConfig} */
const nextConfig = {
  // output: 'standalone' produces a self-contained bundle for Docker deployment.
  // The .next/standalone directory includes only what's needed to run the server,
  // reducing the final Docker image from ~1 GB to ~150 MB.
  // 'as const' is required — without it TypeScript infers type 'string' instead
  // of the literal type '"standalone"', which causes a type error with NextConfig.
  output: "standalone" as const,
};

export default withNextIntl(nextConfig);
