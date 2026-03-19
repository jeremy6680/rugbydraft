import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { NextIntlClientProvider } from "next-intl";
import { getMessages } from "next-intl/server";
import { notFound } from "next/navigation";
import { routing } from "@/i18n/routing";
import "../globals.css";

/* Load Geist fonts and expose them as CSS variables */
const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "RugbyDraft",
  description: "Fantasy rugby avec draft au serpent",
};

interface LocaleLayoutProps {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}

export default async function LocaleLayout({
  children,
  params,
}: LocaleLayoutProps) {
  /* Await params — required in Next.js 15 (async params) */
  const { locale } = await params;

  /* Validate locale — return 404 if not in our supported list */
  if (!routing.locales.includes(locale as "fr")) {
    notFound();
  }

  /* Load messages for the current locale server-side.
   * getMessages() reads from messages/fr.json via request.ts */
  const messages = await getMessages();

  return (
    <html
      lang={locale}
      className={`${geistSans.variable} ${geistMono.variable}`}
    >
      {/*
       * NextIntlClientProvider makes translations available to
       * both Server Components (via getTranslations) and
       * Client Components (via useTranslations).
       */}
      <body className="min-h-svh bg-background text-foreground antialiased">
        <NextIntlClientProvider messages={messages}>
          {children}
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
