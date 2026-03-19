import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

/**
 * Creates a Supabase client for use in Server Components, Server Actions,
 * and Route Handlers (server-side only).
 *
 * Uses createServerClient from @supabase/ssr which reads/writes cookies
 * via Next.js cookies() API — this is how Supabase maintains the session
 * server-side without exposing tokens to the client.
 *
 * Never use this in Client Components — use createBrowserSupabaseClient()
 * from client.ts instead.
 */
export async function createServerSupabaseClient() {
  const cookieStore = await cookies();

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        /* Read a cookie by name */
        getAll() {
          return cookieStore.getAll();
        },
        /* Write cookies — used by Supabase to persist and refresh sessions */
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) => {
              cookieStore.set(name, value, options);
            });
          } catch {
            /* setAll can be called from a Server Component where cookies
             * are read-only. The session will still work as long as the
             * middleware refreshes it — this catch is intentional. */
          }
        },
      },
    },
  );
}
