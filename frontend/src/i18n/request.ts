import { getRequestConfig } from "next-intl/server";
import { routing } from "./routing";

/**
 * Server-side configuration for next-intl.
 *
 * This function runs on every server-side request and provides:
 * - The resolved locale (validated against our supported locales)
 * - The corresponding messages file (messages/fr.json, etc.)
 *
 * next-intl calls this automatically via the middleware — we never
 * call it manually in components.
 */
export default getRequestConfig(async ({ requestLocale }) => {
  /* Await the locale from the request (Next.js 15 async params) */
  const requested = await requestLocale;

  /* Validate the locale — fall back to defaultLocale if unrecognised
   * or undefined (e.g. pages outside the [locale] segment).
   * The nullish coalescing operator ?? guarantees a string type here,
   * which satisfies TypeScript strict mode. */
  const locale: string =
    requested && routing.locales.includes(requested as "fr")
      ? requested
      : routing.defaultLocale;

  return {
    locale,
    /* Dynamically import the messages file for the resolved locale */
    messages: (await import(`../../messages/${locale}.json`)).default,
  };
});
