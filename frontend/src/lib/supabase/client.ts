import { createBrowserClient } from "@supabase/ssr";

/**
 * Creates a Supabase client for use in Client Components (browser-side).
 *
 * Uses createBrowserClient from @supabase/ssr which handles:
 * - Cookie-based session persistence (vs localStorage — more secure)
 * - Automatic token refresh
 *
 * Call this inside Client Components only (files with "use client").
 * For Server Components, use createServerSupabaseClient() instead.
 */
export function createBrowserSupabaseClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );
}
