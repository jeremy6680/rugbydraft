"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { LayoutDashboard, Users, Zap, BarChart2, User } from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface NavItem {
  key: string;
  labelKey: string;
  href: string;
  icon: React.ElementType;
}

// ---------------------------------------------------------------------------
// BottomNav
// ---------------------------------------------------------------------------
// Mobile-only navigation bar, fixed at the bottom of the screen.
// Rendered inside AppShell — hidden on md+ breakpoint via the parent wrapper.
//
// Active detection: pathname.startsWith(href) handles nested routes.
// Active state: icon + label switch to text-primary (crimson #872138).
// Inactive state: text-muted-foreground (#736769).
//
// Accessibility:
//   - <nav> landmark with aria-label
//   - aria-current="page" on the active link (screen reader announcement)
//   - Touch targets: h-16 bar + flex-1 links = minimum 44px height (WCAG 2.5.5)
// ---------------------------------------------------------------------------

export default function BottomNav() {
  const t = useTranslations("nav");
  const pathname = usePathname();
  const locale = useLocale();

  // Nav items — order matches the mockup (left to right).
  // href includes the locale prefix so next-intl routes correctly.
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

  return (
    <nav
      aria-label={t("home")}
      className="fixed bottom-0 left-0 right-0 z-50 border-t border-border bg-background"
    >
      <ul className="flex h-16 items-stretch" role="list">
        {navItems.map((item) => {
          const isActive = pathname.startsWith(item.href);
          const Icon = item.icon;

          return (
            <li key={item.key} className="flex flex-1">
              <Link
                href={item.href}
                aria-current={isActive ? "page" : undefined}
                className="flex w-full flex-col items-center justify-center gap-1 transition-colors"
              >
                <Icon
                  size={22}
                  // Slightly bolder stroke on active — reinforces the active state
                  // without needing a background pill.
                  strokeWidth={isActive ? 2.25 : 1.75}
                  aria-hidden="true"
                  className={
                    isActive ? "text-primary" : "text-muted-foreground"
                  }
                />
                <span
                  className={`font-medium ${
                    isActive ? "text-primary" : "text-muted-foreground"
                  }`}
                  style={{ fontSize: "10px", lineHeight: 1 }}
                >
                  {t(item.labelKey)}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
