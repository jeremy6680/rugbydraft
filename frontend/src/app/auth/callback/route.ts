import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

/**
 * Auth callback route — handles the redirect from Supabase after magic link click.
 *
 * Flow:
 * 1. User clicks magic link in email
 * 2. Supabase redirects to: /auth/callback?code=xxxx
 * 3. This route exchanges the code for a session (PKCE flow)
 * 4. Session cookies are written onto the redirect response
 * 5. User is redirected to /fr/dashboard (or the `next` param destination)
 *
 * This route has no locale prefix — it is a pure API handler, not a page.
 * It is excluded from the next-intl middleware matcher explicitly.
 */
export async function GET(request: NextRequest) {
  const { searchParams, origin } = new URL(request.url);

  const code = searchParams.get("code");
  const next = searchParams.get("next") ?? "/fr/dashboard";

  if (!code) {
    // No code in URL — something went wrong upstream.
    return NextResponse.redirect(`${origin}/fr/login?error=no_code`);
  }

  // Build the redirect response first — we will write cookies onto it.
  const redirectResponse = NextResponse.redirect(`${origin}${next}`);

  const cookieStore = await cookies();

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        // Write session cookies directly onto the redirect response —
        // this guarantees the browser receives them with the 302 redirect.
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value, options }) => {
            redirectResponse.cookies.set(name, value, options);
          });
        },
      },
    },
  );

  const { error } = await supabase.auth.exchangeCodeForSession(code);

  if (error) {
    console.error(
      "[auth/callback] exchangeCodeForSession error:",
      error.message,
    );
    return NextResponse.redirect(`${origin}/fr/login?error=auth_failed`);
  }

  // Session cookies are now on redirectResponse — the browser will store them
  // and the middleware will find them on the next request to /fr/dashboard.
  return redirectResponse;
}
