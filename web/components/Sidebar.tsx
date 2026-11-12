"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { merchant } from "@/lib/merchant";
import { usePoll } from "@/lib/usePoll";

export function Sidebar() {
  const pathname = usePathname();
  const health = usePoll(merchant.health, 5000);
  const queue = usePoll(merchant.reviewQueue, 3000);
  const [mobileOpen, setMobileOpen] = useState(false);

  const pendingCount = queue.data?.length ?? 0;
  const isOnline = Boolean(health.data && !health.error);
  const isConnecting = !health.data && !health.error;

  const navLinks = [
    {
      href: "/",
      label: "Overview",
      badge: undefined,
      icon: (
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
        </svg>
      ),
    },
    {
      href: "/judge",
      label: "Judge Scenarios",
      badge: "S1–S6",
      icon: (
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
          <path strokeLinecap="round" strokeLinejoin="round" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
          <path strokeLinecap="round" strokeLinejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      ),
    },
    {
      href: "/buyer",
      label: "Maya's Agent",
      badge: "PRP Timeline",
      icon: (
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
          <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
        </svg>
      ),
    },
    {
      href: "/merchant",
      label: "Decision Ledger",
      badge: pendingCount > 0 ? `${pendingCount} review` : undefined,
      badgeTone: pendingCount > 0 ? "warn" : "normal",
      icon: (
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
      ),
    },
  ];

  const sidebarContent = (
    <aside className="flex h-full w-56 flex-col justify-between border-r border-[#191d24] bg-[#090909] py-5">
      {/* Top Section */}
      <div className="space-y-6 px-4">
        {/* Brand / Logo */}
        <Link href="/" className="flex items-center gap-2 px-1">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[#2ebd7b] text-xs font-bold text-[#051a10]">
            P
          </div>
          <div>
            <span className="text-base font-bold tracking-tight text-white">Pact</span>
            <span className="ml-1.5 text-[10px] font-mono text-[#6e7681]">v0.3</span>
          </div>
        </Link>

        {/* Navigation list */}
        <nav className="space-y-1">
          {navLinks.map((link) => {
            const active = link.href === "/" ? pathname === "/" : pathname.startsWith(link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                onClick={() => setMobileOpen(false)}
                className={`flex items-center justify-between rounded-lg px-3 py-2 text-xs font-medium transition-colors ${
                  active
                    ? "bg-[#13261c] text-[#2ebd7b]"
                    : "text-[#8b949e] hover:bg-[#121518] hover:text-white"
                }`}
              >
                <div className="flex items-center gap-2.5">
                  <span className={active ? "text-[#2ebd7b]" : "text-[#6e7681]"}>{link.icon}</span>
                  <span>{link.label}</span>
                </div>
                {link.badge && (
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] font-mono font-semibold ${
                      link.badgeTone === "warn"
                        ? "bg-[#2b2210] text-[#eab308]"
                        : active
                        ? "bg-[#1f2620] text-[#2ebd7b]"
                        : "bg-[#161a22] text-[#8b949e]"
                    }`}
                  >
                    {link.badge}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>
      </div>

      {/* Bottom Section: Service Status */}
      <div className="px-4">
        <div className="rounded-xl border border-[#1b1f24] bg-[#0d0f0e] p-3 text-xs">
          <div className="flex items-center justify-between">
            <span className="font-medium text-white">Status</span>
            <span
              className={`flex items-center gap-1 text-[11px] font-medium ${
                isOnline ? "text-[#2ebd7b]" : isConnecting ? "text-[#eab308]" : "text-[#d0545e]"
              }`}
            >
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  isOnline ? "bg-[#2ebd7b]" : isConnecting ? "bg-[#eab308]" : "bg-[#d0545e]"
                }`}
              />
              {isOnline ? "Online" : isConnecting ? "Connecting…" : "Offline"}
            </span>
          </div>

          <div className="mt-2 space-y-1 text-[11px] text-[#8b949e]">
            <div className="flex items-center justify-between">
              <span>PayPal:</span>
              <span className="font-mono text-white">{health.data?.paypal ?? "–"}</span>
            </div>
            <div className="flex items-center justify-between">
              <span>Mode:</span>
              <span className="font-mono text-[#2ebd7b]">{health.data?.mode ?? "–"}</span>
            </div>
          </div>
        </div>
      </div>
    </aside>
  );

  return (
    <>
      {/* Mobile Top Bar */}
      <div className="flex items-center justify-between border-b border-[#1b1f24] bg-[#090909] px-4 py-3 md:hidden">
        <Link href="/" className="flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded bg-[#2ebd7b] text-xs font-bold text-black">
            P
          </div>
          <span className="font-bold text-white text-sm">Pact</span>
        </Link>
        <button
          onClick={() => setMobileOpen(!mobileOpen)}
          className="rounded-lg border border-[#23272f] p-1.5 text-[#8b949e] hover:text-white"
        >
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
      </div>

      {/* Desktop Sticky Sidebar */}
      <div className="hidden md:block md:w-56 md:flex-shrink-0 md:h-screen md:sticky md:top-0">
        {sidebarContent}
      </div>

      {/* Mobile Drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 flex md:hidden">
          <div className="fixed inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setMobileOpen(false)} />
          <div className="relative z-10 w-56">{sidebarContent}</div>
        </div>
      )}
    </>
  );
}
