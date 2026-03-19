import { defineRouting } from "next-intl/routing";

/**
 * Defines the routing configuration for next-intl.
 *
 * V1: French only. Architecture is i18n-ready — adding 'en', 'es', 'it'
 * only requires adding the locale here + the corresponding messages file.
 * No changes to components or business logic needed.
 */
export const routing = defineRouting({
  /* Supported locales — extend here for V2 (EN) and V3 (ES/IT) */
  locales: ["fr"],

  /* Default locale — used when no locale prefix is detected */
  defaultLocale: "fr",

  /* Always include the locale prefix in the URL: /fr/dashboard, /fr/draft
   * Using 'always' (vs 'as-needed') makes URLs explicit and cache-friendly.
   * When we add EN in V2, /en/dashboard will work without any routing change. */
  localePrefix: "always",
});
