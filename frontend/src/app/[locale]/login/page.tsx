import { useTranslations } from "next-intl";
import LoginForm from "@/components/auth/LoginForm";

/**
 * Login page — magic link authentication.
 * Split-screen layout: brand panel (desktop left) + form panel (right).
 * Mobile: form only with logo header.
 */
export default function LoginPage() {
  const t = useTranslations("auth");

  return (
    <div className="min-h-svh flex">
      {/* ── Left panel — brand (desktop only) ── */}
      <div className="hidden lg:flex lg:w-1/2 bg-[#21080E] flex-col justify-between p-12 relative overflow-hidden">
        {/* Hexagonal pattern overlay — rugby jersey texture */}
        <div
          className="absolute inset-0 opacity-[0.04]"
          style={{
            backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='56' height='100'%3E%3Cpath d='M28 66L0 50V16L28 0l28 16v34L28 66zm0 34L0 84V68l28 16 28-16v16L28 100z' fill='none' stroke='%23F2CAD3' stroke-width='1'/%3E%3C/svg%3E")`,
            backgroundSize: "56px 100px",
          }}
          aria-hidden="true"
        />

        {/* Top — logo */}
        <div className="relative z-10">
          <div className="flex items-center gap-3">
            {/* Rugby ball icon — inline SVG, no external dependency */}
            <svg
              width="36"
              height="36"
              viewBox="0 0 36 36"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              aria-hidden="true"
            >
              <ellipse
                cx="18"
                cy="18"
                rx="14"
                ry="9"
                transform="rotate(-35 18 18)"
                fill="#872138"
                stroke="#F2CAD3"
                strokeWidth="1.5"
              />
              <line
                x1="10"
                y1="18"
                x2="26"
                y2="18"
                stroke="#F2CAD3"
                strokeWidth="1"
                strokeDasharray="2 2"
              />
              <line
                x1="18"
                y1="10"
                x2="18"
                y2="26"
                stroke="#F2CAD3"
                strokeWidth="1"
                strokeDasharray="2 2"
              />
            </svg>
            <span className="text-[#F2CAD3] text-xl font-bold tracking-wide">
              RugbyDraft
            </span>
          </div>
        </div>

        {/* Center — headline */}
        <div className="relative z-10 space-y-6">
          <h1 className="text-[#faeef0] text-5xl font-black leading-[1.05] tracking-tight">
            Le fantasy
            <br />
            rugby qui
            <br />
            <span className="text-[#99BF36]">change tout.</span>
          </h1>
          <p className="text-[#b9b3b4] text-lg leading-relaxed max-w-sm">
            Draft au serpent. Chaque joueur appartient à une seule équipe.
            Chaque décision compte.
          </p>
        </div>

        {/* Bottom — tagline */}
        <div className="relative z-10">
          <p className="text-[#4e4647] text-sm">
            Six Nations · Rugby Championship · Top 14
          </p>
        </div>
      </div>

      {/* ── Right panel — form ── */}
      <div className="flex-1 flex flex-col items-center justify-center p-8 bg-background">
        {/* Mobile logo — hidden on desktop */}
        <div className="lg:hidden flex items-center gap-2 mb-10">
          <svg
            width="28"
            height="28"
            viewBox="0 0 36 36"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden="true"
          >
            <ellipse
              cx="18"
              cy="18"
              rx="14"
              ry="9"
              transform="rotate(-35 18 18)"
              fill="#872138"
              stroke="#872138"
              strokeWidth="1.5"
            />
          </svg>
          <span className="text-foreground text-lg font-bold tracking-wide">
            RugbyDraft
          </span>
        </div>

        {/* Form card */}
        <div className="w-full max-w-sm space-y-8">
          <div className="space-y-2">
            <h2 className="text-foreground text-2xl font-bold tracking-tight">
              {t("welcomeBack")}
            </h2>
            <p className="text-muted-foreground text-sm">
              {t("welcomeSubtitle")}
            </p>
          </div>

          {/* Magic link form — Client Component */}
          <LoginForm />
        </div>
      </div>
    </div>
  );
}
