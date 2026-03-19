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
 * 4. Session is stored in cookies
 * 5. User is redirected to /fr/dashboard (or the original destination)
 *
 * This route has no locale prefix — it's a pure API handler, not a page.
 * next-intl middleware matcher excludes it via the file extension pattern.
 */
export async function GET(request: NextRequest) {
  const { searchParams, origin } = new URL(request.url);

  /* The auth code provided by Supabase in the redirect URL */
  const code = searchParams.get("code");

  /* Optional: where to redirect after successful login.
   * Defaults to /fr/dashboard if not specified. */
  const next = searchParams.get("next") ?? "/fr/dashboard";

  if (!code) {
    /* No code in URL — something went wrong upstream.
     * Redirect to login with an error indicator. */
    return NextResponse.redirect(`${origin}/fr/login?error=no_code`);
  }

  const cookieStore = await cookies();

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value, options }) => {
            cookieStore.set(name, value, options);
          });
        },
      },
    },
  );

  /* Exchange the auth code for a session.
   * This creates the auth cookies that the middleware will read
   * on subsequent requests to identify the logged-in user. */
  const { error } = await supabase.auth.exchangeCodeForSession(code);

  if (error) {
    console.error(
      "[auth/callback] exchangeCodeForSession error:",
      error.message,
    );
    return NextResponse.redirect(`${origin}/fr/login?error=auth_failed`);
  }

  /* Session created — redirect to destination */
  return NextResponse.redirect(`${origin}${next}`);
}
