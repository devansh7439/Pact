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
  const [dashboardOpen, setDashboardOpen] = useState(true);
  const [mobileOpen, setMobileOpen] = useState(false);

  const pendingCount = queue.data?.length ?? 0;
  const isOnline = Boolean(health.data && !health.error);
  const isConnecting = !health.data && !health.error;

  const navItem = (label: string, path: string, badge?: string) => {
    const active = path === "/" ? pathname === "/" : pathname.startsWith(path);
    return (
      <Link
        key={path}
        href={path}
        onClick={() => setMobileOpen(false)}
        className={`group relative flex items-center justify-between px-3 py-2 text-xs font-medium rounded-lg transition-all duration-150 ${
          active
            ? "border-l-2 border-[#2ebd7b] bg-[#0c1a14] text-white"
            : "border-l-2 border-transparent text-[#8b949e] hover:bg-[#121518] hover:text-[#e6edf3]"
        }`}
      >
        <span>{label}</span>
        {badge && (
          <span className="rounded bg-[#1a231e] px-1.5 py-0.5 text-[10px] font-semibold text-[#2ebd7b]">
            {badge}
          </span>
        )}
      </Link>
    );
  };

  const navLinks = [
    {
      href: "/judge",
      label: "Judge Mode",
      badge: "S1–S6",
      icon: (
        <svg className="h-4 w-4 text-current" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 6l3 1m0 0l-3 9a5.002 5.002 0 006.001 0M6 7l3 9M6 7l6-2m6 2l3-1m-3 1l-3 9a5.002 5.002 0 006.001 0M18 7l3 9m-3-9l-6-2m0-2v2m0 16V5m0 16H9m3 0h3" />
        </svg>
      ),
    },
    {
      href: "/buyer",
      label: "Maya's Agent",
      badge: "Guard G1–12",
      icon: (
        <svg className="h-4 w-4 text-current" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
          <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
        </svg>
      ),
    },
  ];

  const sidebarContent = (
    <aside className="flex h-full w-60 flex-col justify-between border-r border-[#191d24] bg-[#090909] py-5">
      {/* Top Section */}
      <div className="space-y-6 px-4">
        {/* Brand / Logo */}
        <Link href="/" className="flex items-center gap-2.5 px-1">
          <div className="relative flex h-6 w-8 items-center justify-center">
            <svg
              viewBox="0 0 32 20"
              className="h-5 w-8 text-[#2ebd7b]"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.4"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <rect x="2" y="2" width="20" height="16" rx="8" />
              <path d="M14 6l4-4 4 4" />
              <path d="M18 14l-4 4-4-4" />
            </svg>
          </div>
          <div>
            <span className="text-xl font-bold tracking-tight text-white">pact</span>
            <span className="ml-1.5 text-[10px] font-mono uppercase text-[#6e7681]">v0.1</span>
          </div>
        </Link>

        {/* Navigation list */}
        <nav className="space-y-1.5">
          {/* Dashboard Group */}
          <div>
            <button
              onClick={() => setDashboardOpen(!dashboardOpen)}
              className="flex w-full items-center justify-between rounded-md px-2.5 py-1.5 text-xs font-semibold text-[#2ebd7b] hover:bg-[#0d1612]"
            >
              <div className="flex items-center gap-2.5">
                <svg className="h-3.5 w-3.5 text-[#2ebd7b]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
                </svg>
                <span>Merchant Console</span>
              </div>
              <svg
                className={`h-3 w-3 text-[#2ebd7b] transition-transform duration-200 ${
                  dashboardOpen ? "rotate-0" : "-rotate-90"
                }`}
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth="2.5"
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {/* Dashboard Submenu */}
            {dashboardOpen && (
              <div className="mt-1 space-y-0.5 pl-3">
                {navItem("Overview", "/")}
                {navItem("Decision Ledger", "/merchant", pendingCount > 0 ? `${pendingCount} review` : undefined)}
              </div>
            )}
          </div>

          {/* Divider */}
          <div className="my-3 border-t border-[#191d24]" />

          {/* Peer views */}
          {navLinks.map((link) => {
            const active = pathname.startsWith(link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                onClick={() => setMobileOpen(false)}
                className={`flex items-center justify-between rounded-lg px-2.5 py-2 text-xs font-medium transition-all ${
                  active
                    ? "bg-[#13261c] text-[#2ebd7b]"
                    : "text-[#8b949e] hover:bg-[#121518] hover:text-white"
                }`}
              >
                <div className="flex items-center gap-2.5">
                  {link.icon}
                  <span>{link.label}</span>
                </div>
                <span className="rounded bg-[#1e2420] px-1.5 py-0.5 text-[10px] font-mono text-[#2ebd7b]">
                  {link.badge}
                </span>
              </Link>
            );
          })}
        </nav>
      </div>

      {/* Bottom Section: Real Merchant Status */}
      <div className="space-y-3 px-4 pt-4 border-t border-[#191d24]">
        <div className="rounded-xl bg-[#0d0f0e] p-3 border border-[#1b1f26]">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-white">Kettle &amp; Crumb</span>
            <span className={`flex items-center gap-1 text-[10px] ${
              isOnline ? "text-[#2ebd7b]" : isConnecting ? "text-warn" : "text-[#d0545e]"
            }`}>
              <span className="relative flex h-1.5 w-1.5">
                {isOnline && (
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#2ebd7b] opacity-75" />
                )}
                <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${
                  isOnline ? "bg-[#2ebd7b]" : isConnecting ? "bg-warn" : "bg-[#d0545e]"
                }`} />
              </span>
              {isOnline ? "Online" : isConnecting ? "Connecting…" : "Offline"}
            </span>
          </div>

          <div className="mt-2 space-y-1 text-[11px] text-[#7d8590]">
            <div className="flex items-center justify-between">
              <span>PayPal mode:</span>
              <span className="font-mono text-white">{health.data?.paypal ?? "–"}</span>
            </div>
            <div className="flex items-center justify-between">
              <span>Engine mode:</span>
              <span className="font-mono text-[#2ebd7b]">{health.data?.mode ?? "–"}</span>
            </div>
            <div className="truncate font-mono text-[10px] text-[#6e7681] pt-1">
              {health.error ? "Service unreachable (:8100)" : health.data?.merchant_key_id ?? "loading key…"}
            </div>
          </div>
        </div>
      </div>
    </aside>
  );

  return (
    <>
      {/* Mobile Top Bar */}
      <div className="flex items-center justify-between border-b border-[#1b1f26] bg-[#090909] px-4 py-3 md:hidden">
        <Link href="/" className="flex items-center gap-2">
          <svg viewBox="0 0 32 20" className="h-4 w-6 text-[#2ebd7b]" fill="none" stroke="currentColor" strokeWidth="2.4">
            <rect x="2" y="2" width="20" height="16" rx="8" />
            <path d="M14 6l4-4 4 4" />
            <path d="M18 14l-4 4-4-4" />
          </svg>
          <span className="text-lg font-bold text-white">pact</span>
        </Link>
        <button
          onClick={() => setMobileOpen(!mobileOpen)}
          className="rounded-lg border border-[#23272f] p-1.5 text-white"
        >
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
      </div>

      {/* Desktop Fixed Sidebar */}
      <div className="hidden md:block md:w-60 md:flex-shrink-0 md:h-screen md:sticky md:top-0">
        {sidebarContent}
      </div>

      {/* Mobile Drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 flex md:hidden">
          <div className="fixed inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setMobileOpen(false)} />
          <div className="relative z-10 w-64">{sidebarContent}</div>
        </div>
      )}
    </>
  );
}
