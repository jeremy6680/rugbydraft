import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";
import createIntlMiddleware from "next-intl/middleware";
import { routing } from "@/i18n/routing";

// ---------------------------------------------------------------------------
// next-intl middleware instance
// ---------------------------------------------------------------------------

const intlMiddleware = createIntlMiddleware(routing);

// ---------------------------------------------------------------------------
// Public routes — no session required.
// Matched against pathname with locale prefix removed.
// ---------------------------------------------------------------------------

const PUBLIC_ROUTES = ["/login", "/auth/callback"];

function isPublicRoute(pathname: string): boolean {
  const pathnameWithoutLocale = pathname.replace(/^\/[a-z]{2}(\/|$)/, "/");
  return PUBLIC_ROUTES.some(
    (route) =>
      pathnameWithoutLocale === route ||
      pathnameWithoutLocale.startsWith(`${route}/`),
  );
}

// ---------------------------------------------------------------------------
// middleware
// ---------------------------------------------------------------------------
// Order of operations:
//
// 1. Run next-intl FIRST to get its response (locale rewriting, redirects).
// 2. Create the Supabase client using the intl response as the base —
//    so session cookies are written onto the same response object that
//    next-intl already prepared.
// 3. Check auth and redirect to login if needed.
//
// This approach avoids the "two responses" problem where Supabase cookies
// were written to a response that next-intl then discarded.
// ---------------------------------------------------------------------------

export async function proxy(request: NextRequest) {
  // --- Step 1: Run next-intl first, get its response ---
  // We use this as the base response so locale rewrites are preserved.
  const intlResponse = intlMiddleware(request);

  // --- Step 2: Create Supabase client, writing cookies onto intlResponse ---
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          // Write session cookies onto the intl response — not a new response.
          // This ensures both locale rewrites AND session cookies survive.
          cookiesToSet.forEach(({ name, value, options }) =>
            intlResponse.cookies.set(name, value, options),
          );
        },
      },
    },
  );

  // Validate the session (triggers token refresh if needed).
  const {
    data: { user },
  } = await supabase.auth.getUser();

  // --- Step 3: Protect routes ---
  const { pathname } = request.nextUrl;

  if (!isPublicRoute(pathname) && !user) {
    // Extract locale from URL for a localised redirect.
    const localeMatch = pathname.match(/^\/([a-z]{2})(\/|$)/);
    const locale = localeMatch ? localeMatch[1] : routing.defaultLocale;

    return NextResponse.redirect(new URL(`/${locale}/login`, request.url));
  }

  // Return the intl response with session cookies attached.
  return intlResponse;
}

export const config = {
  matcher: [
    /*
     * Match all request paths EXCEPT:
     * - _next/static, _next/image  (Next.js internals)
     * - favicon.ico
     * - Static assets (images, fonts, etc.)
     * - auth/callback              (Supabase Auth handler — no locale prefix)
     */
    "/((?!_next/static|_next/image|favicon.ico|auth/callback|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|css|js|woff|woff2|ttf|otf)$).*)",
  ],
};
