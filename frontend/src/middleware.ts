import { createServerClient } from "@supabase/ssr";
import { type NextRequest, NextResponse } from "next/server";
import createIntlMiddleware from "next-intl/middleware";
import { routing } from "@/i18n/routing";

/**
 * Combined middleware: Supabase Auth session refresh + next-intl locale routing.
 *
 * Order matters:
 * 1. Supabase refreshes the session cookie on every request — this must run
 *    first so that Server Components receive a valid session.
 * 2. next-intl handles locale detection and URL redirects (/→/fr).
 *
 * Why chain them manually instead of using next-intl's built-in auth?
 * Because Supabase requires direct access to the NextResponse object to
 * set cookies — next-intl's middleware wrapper doesn't expose this.
 */

/* next-intl middleware instance — reused on every request */
const intlMiddleware = createIntlMiddleware(routing);

export async function middleware(request: NextRequest) {
  /* Start with a basic response that next-intl can modify */
  let response = NextResponse.next({
    request: {
      headers: request.headers,
    },
  });

  /* Step 1 — Supabase: refresh session cookie if expired.
   * This keeps the user logged in across page navigations.
   * We use the anon key here — the session token is in the cookie. */
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          /* Write updated cookies to both the request and response */
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value),
          );
          response = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options),
          );
        },
      },
    },
  );

  /* Refresh session — do not remove this call.
   * It's a no-op if the session is still valid, but essential when
   * the access token has expired and needs to be refreshed via the
   * refresh token stored in the cookie. */
  await supabase.auth.getUser();

  /* Step 2 — next-intl: handle locale detection and URL redirects */
  const intlResponse = intlMiddleware(request);

  /* If next-intl wants to redirect (e.g. / → /fr), honour that redirect
   * but carry over any cookies Supabase may have set */
  if (intlResponse.status !== 200) {
    /* Copy Supabase cookies onto the intl redirect response */
    response.cookies.getAll().forEach((cookie) => {
      intlResponse.cookies.set(cookie.name, cookie.value);
    });
    return intlResponse;
  }

  return response;
}

export const config = {
  matcher: [
    /*
     * Match all request paths EXCEPT:
     * - _next/static  (static files)
     * - _next/image   (image optimisation)
     * - favicon.ico   (favicon)
     * - Files with extensions (images, fonts, etc.)
     */
    "/((?!_next/static|_next/image|favicon.ico|.*\\..*).*)",
  ],
};
