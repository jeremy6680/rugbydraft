"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { createBrowserSupabaseClient } from "@/lib/supabase/client";

/**
 * LoginForm — Client Component.
 *
 * Handles magic link authentication via Supabase Auth.
 * "use client" is required because we use useState and browser events.
 *
 * Flow:
 * 1. User enters email and submits
 * 2. Supabase sends a magic link to the email
 * 3. User clicks the link → redirected to /auth/callback → session created
 * 4. Middleware detects valid session → redirects to /fr/dashboard
 */
export default function LoginForm() {
  const t = useTranslations("auth");

  const [email, setEmail] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isSent, setIsSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setIsLoading(true);
    setError(null);

    const supabase = createBrowserSupabaseClient();

    const { error: supabaseError } = await supabase.auth.signInWithOtp({
      email,
      options: {
        /* Redirect URL after clicking the magic link.
         * In development: http://localhost:3000/auth/callback
         * In production: https://rugbydraft.app/auth/callback
         * The /auth/callback route will be created next. */
        emailRedirectTo: `${window.location.origin}/auth/callback`,
      },
    });

    if (supabaseError) {
      setError(supabaseError.message);
      setIsLoading(false);
      return;
    }

    setIsSent(true);
    setIsLoading(false);
  }

  /* ── Success state — magic link sent ── */
  if (isSent) {
    return (
      <div className="space-y-4">
        {/* Success card */}
        <div className="rounded-xl border border-[#99BF36]/30 bg-[#99BF36]/10 p-6 space-y-2">
          {/* Checkmark icon */}
          <div className="flex items-center gap-3">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-[#99BF36] flex items-center justify-center">
              <svg
                width="16"
                height="16"
                viewBox="0 0 16 16"
                fill="none"
                aria-hidden="true"
              >
                <path
                  d="M3 8l3.5 3.5L13 4"
                  stroke="#0d1302"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </div>
            <p className="text-foreground font-semibold text-sm">
              {t("magicLinkSent")}
            </p>
          </div>
          <p className="text-muted-foreground text-xs pl-11">
            Lien envoyé à{" "}
            <span className="font-medium text-foreground">{email}</span>
          </p>
        </div>

        {/* Retry link */}
        <button
          type="button"
          onClick={() => {
            setIsSent(false);
            setEmail("");
          }}
          className="text-sm text-muted-foreground hover:text-primary transition-colors underline underline-offset-4"
        >
          Utiliser une autre adresse
        </button>
      </div>
    );
  }

  /* ── Default state — email form ── */
  return (
    <form onSubmit={handleSubmit} className="space-y-5" noValidate>
      {/* Email field */}
      <div className="space-y-2">
        <label htmlFor="email" className="text-sm font-medium text-foreground">
          Adresse email
        </label>
        <input
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          required
          placeholder={t("magicLinkPlaceholder")}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          disabled={isLoading}
          className="
            w-full rounded-lg border border-border bg-card
            px-4 py-3 text-sm text-foreground
            placeholder:text-muted-foreground
            focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent
            disabled:opacity-50 disabled:cursor-not-allowed
            transition-colors
          "
          aria-describedby={error ? "login-error" : undefined}
        />
      </div>

      {/* Error message */}
      {error && (
        <p id="login-error" role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}

      {/* Submit button */}
      <button
        type="submit"
        disabled={isLoading || !email}
        className="
          w-full rounded-lg bg-primary px-4 py-3
          text-sm font-semibold text-primary-foreground
          hover:bg-[#6d1a2d] active:bg-[#50101e]
          focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2
          disabled:opacity-50 disabled:cursor-not-allowed
          transition-colors
        "
        aria-busy={isLoading}
      >
        {isLoading ? (
          <span className="flex items-center justify-center gap-2">
            {/* Spinner */}
            <svg
              className="animate-spin h-4 w-4"
              viewBox="0 0 24 24"
              fill="none"
              aria-hidden="true"
            >
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8v8H4z"
              />
            </svg>
            Envoi en cours…
          </span>
        ) : (
          t("loginWithMagicLink")
        )}
      </button>

      {/* Divider */}
      <div className="relative">
        <div className="absolute inset-0 flex items-center" aria-hidden="true">
          <div className="w-full border-t border-border" />
        </div>
        <div className="relative flex justify-center">
          <span className="bg-background px-3 text-xs text-muted-foreground">
            Google OAuth disponible prochainement
          </span>
        </div>
      </div>

      {/* Terms */}
      <p className="text-xs text-muted-foreground text-center leading-relaxed">
        En continuant, vous acceptez nos{" "}
        <a
          href="#"
          className="underline underline-offset-4 hover:text-foreground transition-colors"
        >
          conditions d&apos;utilisation
        </a>
        .
      </p>
    </form>
  );
}
