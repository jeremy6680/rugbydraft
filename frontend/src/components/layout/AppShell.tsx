import Sidebar from "@/components/layout/Sidebar";
import BottomNav from "@/components/layout/BottomNav";
import { getTranslations } from "next-intl/server";

// ---------------------------------------------------------------------------
// AppShell
// ---------------------------------------------------------------------------
// Structural layout wrapper for all authenticated pages.
// Renders the persistent navigation (Sidebar on desktop, BottomNav on mobile)
// alongside the page content passed as children.
//
// This component is a Server Component — no state, no hooks.
// It is rendered by the (protected) group layout, which ensures it is never
// shown on public pages (login, landing, etc.).
//
// Layout structure:
//   - Skip-to-content link (visually hidden, visible on focus — WCAG 2.4.1)
//   - Full-height flex row: [Sidebar | main content area]
//   - Sidebar: sticky, desktop only (hidden on mobile via md:flex in Sidebar)
//   - BottomNav: fixed bottom, mobile only (hidden on desktop via md:hidden)
//   - main: scrollable, pb-16 on mobile to clear the fixed BottomNav
// ---------------------------------------------------------------------------

interface AppShellProps {
  children: React.ReactNode;
}

export default async function AppShell({ children }: AppShellProps) {
  // Server-side translation for the skip link — AppShell is a Server Component.
  const t = await getTranslations("common");

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Skip-to-content link — visually hidden until focused.
          Required for WCAG 2.4.1 (keyboard navigation bypass).
          Becomes visible when tabbed to, positioned above all other content. */}
      <a
        href="#main-content"
        className="
          sr-only focus:not-sr-only
          focus:fixed focus:top-4 focus:left-4 focus:z-[100]
          focus:rounded-md focus:bg-primary focus:px-4 focus:py-2
          focus:text-primary-foreground focus:text-sm focus:font-medium
          focus:shadow-md focus:outline-none
        "
      >
        {t("skipToContent")}
      </a>

      {/* Desktop sidebar — renders itself as hidden on mobile */}
      <Sidebar />

      {/* Right-hand column: page content + mobile nav */}
      <div className="flex flex-1 flex-col overflow-hidden">
        <main
          id="main-content"
          // tabIndex={-1} allows the skip link to programmatically focus this element.
          tabIndex={-1}
          // overflow-y-auto: page content scrolls independently of the sidebar.
          // pb-16: clears the fixed BottomNav on mobile (h-16 = 64px).
          // md:pb-0: no padding needed on desktop (BottomNav is hidden).
          // outline-none: suppress focus ring on main (it receives focus from skip link only).
          className="flex-1 overflow-y-auto pb-16 md:pb-0 outline-none"
        >
          {children}
        </main>

        {/* Mobile bottom nav — renders itself as hidden on desktop */}
        <BottomNav />
      </div>
    </div>
  );
}
