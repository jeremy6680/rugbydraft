import createNextIntlPlugin from "next-intl/plugin";

/**
 * next-intl plugin — points to our request config file.
 * This tells next-intl where to find the server-side configuration
 * (locale resolution + messages loading).
 */
const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

/** @type {import('next').NextConfig} */
const nextConfig = {};

export default withNextIntl(nextConfig);
