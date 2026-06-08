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
  const { searchParams } = new URL(request.url);
  const code = searchParams.get("code");
  const next = searchParams.get("next") ?? "/fr/dashboard";

  // Use the public app URL — never derive origin from request.url
  // behind a reverse proxy (Traefik), request.url contains the internal
  // container address (0.0.0.0:3000), not the public domain.
  const appUrl = process.env.NEXT_PUBLIC_APP_URL ?? "https://rugbydraft.app";

  if (!code) {
    return NextResponse.redirect(`${appUrl}/fr/login?error=no_code`);
  }

  const redirectResponse = NextResponse.redirect(`${appUrl}${next}`);
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
    return NextResponse.redirect(`${appUrl}/fr/login?error=auth_failed`);
  }

  return redirectResponse;
}
