import "@/styles/globals.css";
import type { AppProps } from "next/app";
import Link from "next/link";
import { useRouter } from "next/router";
import { Outfit, JetBrains_Mono } from "next/font/google";

const outfit = Outfit({
  subsets: ["latin"],
  variable: "--font-outfit",
  display: "swap",
});

const jetbrains = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains",
  display: "swap",
});

const nav = [
  { href: "/", label: "Overview" },
  { href: "/model", label: "Model" },
  { href: "/agent", label: "Agent" },
];

export default function App({ Component, pageProps }: AppProps) {
  const router = useRouter();

  return (
    <div className={`${outfit.variable} ${jetbrains.variable} app-shell`}>
      <header className="app-nav">
        <div className="app-brand">
          <strong>MSFT Corporate Finance Autopilot</strong>
          <small>Deterministic model · RAG agent · Audit trail</small>
        </div>
        <nav className="nav-links" aria-label="Primary">
          {nav.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              className={`nav-link ${router.pathname === href ? "active" : ""}`}
            >
              {label}
            </Link>
          ))}
        </nav>
      </header>
      <Component {...pageProps} />
    </div>
  );
}
