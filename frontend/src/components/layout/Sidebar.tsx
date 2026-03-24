"use client";

import { useState, useEffect } from "react";
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

// localStorage key for persisting collapsed state across sessions.
const STORAGE_KEY = "rugbydraft:sidebar-collapsed";

// ---------------------------------------------------------------------------
// Sidebar
// ---------------------------------------------------------------------------
// Desktop-only navigation sidebar (hidden on mobile — BottomNav is used instead).
//
// Two states:
//   - Expanded (240px): logo text + icon + label
//   - Collapsed (64px): initials "RD" + icon only (tooltip on hover)
//
// Hydration strategy:
//   - Server renders the sidebar in its default expanded state (collapsed=false).
//   - After mount, useEffect reads localStorage and updates if needed.
//   - The `mounted` flag prevents rendering until localStorage is read,
//     avoiding a flash of the wrong state.
//   - While !mounted, we render a same-width placeholder so the layout
//     does not shift when the sidebar appears.
// ---------------------------------------------------------------------------

export default function Sidebar() {
  const t = useTranslations("nav");
  const tSidebar = useTranslations("sidebar");
  const pathname = usePathname();
  const locale = useLocale();

  // Default false — matches server render. Updated after mount from localStorage.
  const [isCollapsed, setIsCollapsed] = useState<boolean | null>(null);

  // True once localStorage has been read. Prevents hydration mismatch.
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    // This runs once after mount — localStorage is safe to access here.
    // We initialise the state from persisted value only once.
    const stored = localStorage.getItem(STORAGE_KEY) === "true";
    // Use a ref-style update to avoid the setState-in-effect warning:
    // we call setState inside useEffect but gated on a one-time init flag.
    if (isCollapsed === null) {
      setIsCollapsed(stored);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

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

  // ---------------------------------------------------------------------------
  // Pre-mount placeholder
  // Renders an empty sidebar shell with the correct default width.
  // Keeps layout stable while localStorage is being read.
  // ---------------------------------------------------------------------------

  if (isCollapsed === null) {
    return (
      <div
        aria-hidden="true"
        className="hidden md:flex h-screen w-60 shrink-0 bg-foreground border-r border-border"
      />
    );
  }

  // ---------------------------------------------------------------------------
  // Main render
  // ---------------------------------------------------------------------------

  return (
    <TooltipProvider delayDuration={300}>
      <aside
        className={`
          hidden md:flex flex-col
          h-screen sticky top-0 shrink-0
          bg-foreground text-primary-foreground
          border-r border-border
          transition-all duration-200 ease-in-out overflow-hidden
          ${isCollapsed ? "w-16" : "w-60"}
        `}
      >
        {/* Header: logo + toggle button */}
        <div className="flex h-16 items-center justify-between px-3 shrink-0">
          {isCollapsed ? (
            <span className="text-rose-100 font-semibold text-sm mx-auto">
              RD
            </span>
          ) : (
            <span className="text-rose-100 font-semibold text-sm tracking-wide truncate">
              RugbyDraft
            </span>
          )}

          <button
            aria-expanded={!isCollapsed}
            aria-label={isCollapsed ? tSidebar("expand") : tSidebar("collapse")}
            className={`
              flex items-center justify-center
              w-8 h-8 rounded-md shrink-0
              text-rose-100 opacity-60
              hover:opacity-100 hover:bg-crimson-500
              transition-all duration-150
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-400
              ${isCollapsed ? "mx-auto" : "ml-2"}
            `}
            onClick={handleToggle}
          >
            {isCollapsed ? (
              <PanelLeftOpen aria-hidden="true" size={16} />
            ) : (
              <PanelLeftClose aria-hidden="true" size={16} />
            )}
          </button>
        </div>

        {/* Navigation items */}
        <nav aria-label={tSidebar("ariaLabel")} className="flex-1 px-2 py-2">
          <ul className="flex flex-col gap-1" role="list">
            {navItems.map((item) => {
              const isActive = pathname.startsWith(item.href);
              const Icon = item.icon;

              const linkContent = (
                <Link
                  aria-current={isActive ? "page" : undefined}
                  className={`
                    flex items-center gap-3
                    rounded-md px-2 py-2
                    transition-colors duration-150
                    focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-400
                    ${
                      isActive
                        ? "bg-crimson-500/20 border-l-2 border-primary text-rose-100"
                        : "border-l-2 border-transparent text-rose-100/50 hover:bg-crimson-500/10 hover:text-rose-100/80"
                    }
                    ${isCollapsed ? "justify-center" : ""}
                  `}
                  href={item.href}
                >
                  <Icon
                    aria-hidden="true"
                    className="shrink-0"
                    size={18}
                    strokeWidth={isActive ? 2.25 : 1.75}
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
