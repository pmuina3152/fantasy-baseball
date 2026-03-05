"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/rankings",      label: "Rankings"       },
  { href: "/team-builder",  label: "Team Builder"   },
  { href: "/trade-analyzer",label: "Trade Analyzer" },
] as const;

export default function Nav() {
  const pathname = usePathname();

  return (
    <nav className="border-b border-gray-800 bg-gray-900/95 backdrop-blur-sm">
      <div className="max-w-screen-2xl mx-auto px-4 sm:px-6 flex items-center gap-1 h-12">
        {/* Brand */}
        <Link
          href="/rankings"
          className="mr-4 text-sm font-bold text-white tracking-tight whitespace-nowrap"
        >
          ⚾ Fantasy BB
        </Link>

        {/* Page links */}
        {LINKS.map(({ href, label }) => {
          const active = pathname === href || pathname.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors whitespace-nowrap ${
                active
                  ? "bg-blue-600 text-white"
                  : "text-gray-400 hover:text-white hover:bg-gray-800"
              }`}
            >
              {label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
