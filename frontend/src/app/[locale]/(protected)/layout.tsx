import { redirect } from "next/navigation";
import { getLocale } from "next-intl/server";
import { createServerSupabaseClient } from "@/lib/supabase/server";
import AppShell from "@/components/layout/AppShell";

// ---------------------------------------------------------------------------
// Protected layout
// ---------------------------------------------------------------------------
// Wraps all authenticated pages with two responsibilities:
//
// 1. SESSION GUARD — verifies the Supabase session server-side.
//    If no valid session exists, redirects to /[locale]/login.
//    This is the second layer of protection after middleware.ts.
//
// 2. APP SHELL — renders the persistent navigation (Sidebar + BottomNav)
//    around the page content.
//
// This layout is a Server Component — the session check happens before
// any page content is rendered or sent to the client.
//
// Route group (protected) means this layout applies to all pages inside
// this folder without affecting the URL structure.
// ---------------------------------------------------------------------------

interface ProtectedLayoutProps {
  children: React.ReactNode;
}

export default async function ProtectedLayout({
  children,
}: ProtectedLayoutProps) {
  const supabase = await createServerSupabaseClient();
  const locale = await getLocale();

  // Verify the session. getUser() makes a network call to Supabase Auth
  // to validate the JWT — more secure than getSession() which only reads
  // the local cookie without revalidation.
  const {
    data: { user },
    error,
  } = await supabase.auth.getUser();

  // Redirect to login if no valid session.
  // This catches: unauthenticated users, expired tokens, invalid JWTs.
  if (!user || error) {
    redirect(`/${locale}/login`);
  }

  // Session is valid — render the AppShell with the page content.
  return <AppShell>{children}</AppShell>;
}
