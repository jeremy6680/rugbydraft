"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import {
  LayoutDashboard,
  Users,
  Zap,
  BarChart2,
  User,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface NavItem {
  key: string;
  labelKey: string;
  href: string;
  icon: React.ElementType;
}

// localStorage key for persisting the collapsed state across sessions.
const STORAGE_KEY = "rugbydraft:sidebar-collapsed";

// ---------------------------------------------------------------------------
// Sidebar
// ---------------------------------------------------------------------------
// Desktop-only navigation sidebar (hidden on mobile — AppShell renders
// BottomNav instead).
//
// Two states:
//   - Expanded (240px): logo text + icon + label for each nav item
//   - Collapsed (64px): initials "RD" + icon only (tooltip on hover)
//
// Collapsed state is persisted in localStorage.
//
// Hydration strategy: the component renders null until mounted.
// This avoids a server/client mismatch on the collapsed state,
// since localStorage is only available in the browser.
// The sidebar appears after the first client paint — imperceptible in practice.
//
// Accessibility:
//   - <nav> landmark with aria-label
//   - aria-current="page" on active link
//   - aria-expanded on the toggle button
//   - Tooltips on collapsed items (keyboard + mouse accessible)
// ---------------------------------------------------------------------------

export default function Sidebar() {
  const t = useTranslations("nav");
  const tSidebar = useTranslations("sidebar");
  const pathname = usePathname();
  const locale = useLocale();

  // isCollapsed is undefined until we've read localStorage (client only).
  // Rendering null until mounted prevents hydration mismatch entirely.
  const [isCollapsed, setIsCollapsed] = useState<boolean | undefined>(
    undefined,
  );

  // Read localStorage once after first client render.
  // Single setState call — no cascade.
  useEffect(() => {
    setIsCollapsed(localStorage.getItem(STORAGE_KEY) === "true");
  }, []);

  // Persist to localStorage on every toggle.
  const handleToggle = () => {
    setIsCollapsed((prev) => {
      const next = !prev;
      localStorage.setItem(STORAGE_KEY, String(next));
      return next;
    });
  };

  const navItems: NavItem[] = [
    {
      key: "home",
      labelKey: "home",
      href: `/${locale}/dashboard`,
      icon: LayoutDashboard,
    },
    {
      key: "league",
      labelKey: "league",
      href: `/${locale}/league`,
      icon: Users,
    },
    {
      key: "draft",
      labelKey: "draft",
      href: `/${locale}/draft`,
      icon: Zap,
    },
    {
      key: "stats",
      labelKey: "stats",
      href: `/${locale}/stats`,
      icon: BarChart2,
    },
    {
      key: "account",
      labelKey: "account",
      href: `/${locale}/account`,
      icon: User,
    },
  ];

  // Render nothing until the client has read localStorage.
  // This keeps the server-rendered HTML and client HTML in sync.
  if (isCollapsed === undefined) return null;

  return (
    <TooltipProvider delayDuration={300}>
      <aside
        className={`
          hidden md:flex flex-col
          h-screen sticky top-0
          bg-foreground text-primary-foreground
          border-r border-border
          transition-all duration-200 ease-in-out overflow-hidden
          ${isCollapsed ? "w-16" : "w-60"}
        `}
      >
        {/* ----------------------------------------------------------------
            Header: logo + toggle button
        ---------------------------------------------------------------- */}
        <div className="flex h-16 items-center justify-between px-3 shrink-0">
          {!isCollapsed && (
            <span className="text-rose-100 font-semibold text-sm tracking-wide truncate">
              RugbyDraft
            </span>
          )}

          {isCollapsed && (
            <span className="text-rose-100 font-semibold text-sm mx-auto">
              RD
            </span>
          )}

          <button
            onClick={handleToggle}
            aria-expanded={!isCollapsed}
            aria-label={isCollapsed ? tSidebar("expand") : tSidebar("collapse")}
            className={`
              flex items-center justify-center
              w-8 h-8 rounded-md
              text-rose-100 opacity-60
              hover:opacity-100 hover:bg-crimson-500
              transition-all duration-150
              shrink-0
              ${isCollapsed ? "mx-auto" : "ml-2"}
            `}
          >
            {isCollapsed ? (
              <PanelLeftOpen size={16} aria-hidden="true" />
            ) : (
              <PanelLeftClose size={16} aria-hidden="true" />
            )}
          </button>
        </div>

        {/* ----------------------------------------------------------------
            Navigation items
        ---------------------------------------------------------------- */}
        <nav aria-label={tSidebar("ariaLabel")} className="flex-1 px-2 py-2">
          <ul className="flex flex-col gap-1" role="list">
            {navItems.map((item) => {
              const isActive = pathname.startsWith(item.href);
              const Icon = item.icon;

              const linkContent = (
                <Link
                  href={item.href}
                  aria-current={isActive ? "page" : undefined}
                  className={`
                    flex items-center gap-3
                    rounded-md px-2 py-2
                    transition-colors duration-150
                    ${
                      isActive
                        ? "bg-crimson-500/20 border-l-2 border-primary text-rose-100"
                        : "border-l-2 border-transparent text-rose-100/50 hover:bg-crimson-500/10 hover:text-rose-100/80"
                    }
                    ${isCollapsed ? "justify-center" : ""}
                  `}
                >
                  <Icon
                    size={18}
                    strokeWidth={isActive ? 2.25 : 1.75}
                    aria-hidden="true"
                    className="shrink-0"
                  />
                  {!isCollapsed && (
                    <span className="text-sm font-medium truncate">
                      {t(item.labelKey)}
                    </span>
                  )}
                </Link>
              );

              return (
                <li key={item.key}>
                  {isCollapsed ? (
                    <Tooltip>
                      <TooltipTrigger asChild>{linkContent}</TooltipTrigger>
                      <TooltipContent side="right">
                        <p>{t(item.labelKey)}</p>
                      </TooltipContent>
                    </Tooltip>
                  ) : (
                    linkContent
                  )}
                </li>
              );
            })}
          </ul>
        </nav>
      </aside>
    </TooltipProvider>
  );
}
