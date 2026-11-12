"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { Checklist } from "@/components/Checklist";
import { buyer, type InboxMessage, type MandateBody, type Purchase } from "@/lib/buyer";
import { fmt } from "@/lib/money";
import { usePoll } from "@/lib/usePoll";

interface MockTransaction {
  id: string;
  name: string;
  subtitle: string;
  amount: string;
  rail: string;
  status: "approved" | "pending" | "funded";
  iconType: "agent" | "pending" | "fund";
  date: string;
}

const DEFAULT_TRANSACTIONS: MockTransaction[] = [
  {
    id: "tx-aws",
    name: "Procurement Agent → AWS",
    subtitle: "Auto-approved · 2 min ago",
    amount: "-$47.20",
    rail: "ACH",
    status: "approved",
    iconType: "agent",
    date: "2 min ago",
  },
  {
    id: "tx-ins",
    name: "Insurance Agent → Claimant",
    subtitle: "Awaiting approval · $4,800",
    amount: "PENDING",
    rail: "Wire",
    status: "pending",
    iconType: "pending",
    date: "12 min ago",
  },
  {
    id: "tx-dev",
    name: "Dev Agent → Vercel",
    subtitle: "Auto-approved · 18 min ago",
    amount: "-$20.00",
    rail: "ACH",
    status: "approved",
    iconType: "agent",
    date: "18 min ago",
  },
  {
    id: "tx-fund",
    name: "Wallet funded",
    subtitle: "jesse@r1vs.com · Today 9:02am",
    amount: "+$5,000.00",
    rail: "ACH",
    status: "funded",
    iconType: "fund",
    date: "Today 9:02am",
  },
  {
    id: "tx-res",
    name: "Research Agent → DataAPI.io",
    subtitle: "Auto-approved · Yesterday",
    amount: "-$12.50",
    rail: "ACH",
    status: "approved",
    iconType: "agent",
    date: "Yesterday",
  },
];

export default function BuyerPage() {
  const health = usePoll(buyer.health, 5000);
  const mandates = usePoll(buyer.mandates, 5000);
  const purchases = usePoll(buyer.purchases, 2500);
  const inbox = usePoll(buyer.inbox, 2500);
  const budget = usePoll(() => buyer.budget().catch(() => null), 2500);

  const activeMandate = mandates.data?.find((m) => m.status === "ACTIVE") ?? null;
  const draftMandate = mandates.data?.find((m) => m.status === "DRAFT") ?? null;

  // Modals & UI View State
  const [approvalsModalOpen, setApprovalsModalOpen] = useState(false);
  const [addFundsModalOpen, setAddFundsModalOpen] = useState(false);
  const [rulesModalOpen, setRulesModalOpen] = useState(false);
  const [agentsModalOpen, setAgentsModalOpen] = useState(false);
  const [keysModalOpen, setKeysModalOpen] = useState(false);
  const [viewAll, setViewAll] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Conversational command state
  const [chatText, setChatText] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [chatReply, setChatReply] = useState<string | null>(null);

  // Listen to sidebar custom events
  useEffect(() => {
    const handleApprovals = () => setApprovalsModalOpen(true);
    const handleWallet = () => setAddFundsModalOpen(true);
    const handleRules = () => setRulesModalOpen(true);
    const handleAgents = () => setAgentsModalOpen(true);
    const handleKeys = () => setKeysModalOpen(true);
    const handleScroll = () => {
      const el = document.getElementById("transactions-section");
      if (el) el.scrollIntoView({ behavior: "smooth" });
    };

    window.addEventListener("open-approvals-modal", handleApprovals);
    window.addEventListener("open-wallet-modal", handleWallet);
    window.addEventListener("open-rules-modal", handleRules);
    window.addEventListener("open-agents-modal", handleAgents);
    window.addEventListener("open-keys-modal", handleKeys);
    window.addEventListener("scroll-transactions", handleScroll);

    return () => {
      window.removeEventListener("open-approvals-modal", handleApprovals);
      window.removeEventListener("open-wallet-modal", handleWallet);
      window.removeEventListener("open-rules-modal", handleRules);
      window.removeEventListener("open-agents-modal", handleAgents);
      window.removeEventListener("open-keys-modal", handleKeys);
      window.removeEventListener("scroll-transactions", handleScroll);
    };
  }, []);

  const pendingEscalations = inbox.data?.filter((m) => m.kind === "ESCALATION" && m.status !== "DISMISSED") ?? [];
  const pendingApprovalsCount = pendingEscalations.length > 0 ? pendingEscalations.length : 3;

  async function handleSendChat() {
    if (!chatText.trim()) return;
    setChatBusy(true);
    setChatReply(null);
    try {
      if (activeMandate) {
        const res = await buyer.chat(chatText);
        setChatReply(res.reply);
      } else {
        const res = await buyer.draftMandate(chatText);
        setChatReply(`Drafted mandate ${res.mandate_id}. Review and approve it.`);
      }
      setChatText("");
      purchases.refresh();
      inbox.refresh();
      budget.refresh();
      mandates.refresh();
    } catch (e) {
      setChatReply(e instanceof Error ? e.message : String(e));
    } finally {
      setChatBusy(false);
    }
  }

  return (
    <div className="space-y-6 pb-12">
      {/* Top Header matching reference */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">Dashboard</h1>
          <p className="text-xs text-[#71717a] mt-0.5">
            Good morning, Jesse. Here&apos;s what&apos;s moving.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={() => setAddFundsModalOpen(true)}
            className="rounded-lg border border-[#262338] bg-[#12111c] px-3.5 py-2 text-xs font-semibold text-white hover:bg-[#1a1829] transition-all"
          >
            + Add Funds
          </button>
          <button
            onClick={() => setApprovalsModalOpen(true)}
            className="flex items-center gap-1.5 rounded-lg bg-[#7c3aed] px-4 py-2 text-xs font-semibold text-white shadow-md shadow-purple-900/40 hover:bg-[#6d28d9] transition-all"
          >
            <span>Review Approvals</span>
            <span className="font-bold">({pendingApprovalsCount})</span>
          </button>
        </div>
      </div>

      {/* Top 4 Metric Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {/* Card 1: Wallet Balance */}
        <div className="rounded-2xl border border-[#1b1928] bg-[#0c0b13] p-5 shadow-sm">
          <div className="text-[10px] font-bold tracking-wider text-[#52525b] uppercase">
            Wallet Balance
          </div>
          <div className="mt-2 text-2xl font-bold tracking-tight text-white">
            $4,250.00
          </div>
          <div className="mt-1 flex items-center justify-between text-xs text-[#71717a]">
            <span>Available to spend</span>
            {budget.data && (
              <span className="text-[10px] text-[#a855f7] font-mono">
                {fmt(budget.data.remaining_minor, budget.data.currency_code)} Maya pool
              </span>
            )}
          </div>
        </div>

        {/* Card 2: Spent This Week */}
        <div className="rounded-2xl border border-[#1b1928] bg-[#0c0b13] p-5 shadow-sm">
          <div className="text-[10px] font-bold tracking-wider text-[#52525b] uppercase">
            Spent This Week
          </div>
          <div className="mt-2 text-2xl font-bold tracking-tight text-white">
            $1,847.32
          </div>
          <div className="mt-1 flex items-center justify-between text-xs text-[#71717a]">
            <span>↑ 23% vs last week</span>
            {budget.data && (
              <span className="text-[10px] text-[#2ebd7b] font-mono">
                {fmt(budget.data.spent_minor, budget.data.currency_code)} Maya
              </span>
            )}
          </div>
        </div>

        {/* Card 3: Active Agents */}
        <div className="rounded-2xl border border-[#1b1928] bg-[#0c0b13] p-5 shadow-sm">
          <div className="text-[10px] font-bold tracking-wider text-[#52525b] uppercase">
            Active Agents
          </div>
          <div className="mt-2 text-2xl font-bold tracking-tight text-white">
            7
          </div>
          <div className="mt-1 flex items-center justify-between text-xs text-[#71717a]">
            <span>2 pending registration</span>
            <span className="text-[10px] text-[#2ebd7b]">Maya online</span>
          </div>
        </div>

        {/* Card 4: Pending Approval */}
        <div className="rounded-2xl border border-[#1b1928] bg-[#0c0b13] p-5 shadow-sm">
          <div className="text-[10px] font-bold tracking-wider text-[#52525b] uppercase">
            Pending Approval
          </div>
          <div className="mt-2 text-2xl font-bold tracking-tight text-[#f59e0b]">
            {pendingApprovalsCount}
          </div>
          <div className="mt-1 flex items-center justify-between text-xs text-[#71717a]">
            <span>$6,200 total flagged</span>
            {pendingEscalations.length > 0 && (
              <span className="text-[10px] text-[#f59e0b] font-medium">Needs signoff</span>
            )}
          </div>
        </div>
      </div>

      {/* Main 2-Column Section */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Left Column (8 cols): Recent Transactions */}
        <div id="transactions-section" className="lg:col-span-8 space-y-6">
          <div className="rounded-2xl border border-[#1b1928] bg-[#0c0b13] p-6 shadow-sm">
            <div className="flex items-center justify-between border-b border-[#181624] pb-4">
              <h2 className="text-sm font-bold text-white">Recent Transactions</h2>
              <button
                onClick={() => setViewAll(!viewAll)}
                className="text-xs font-semibold text-[#8b5cf6] hover:text-[#a78bfa] transition-colors"
              >
                {viewAll ? "Show less ←" : "View all →"}
              </button>
            </div>

            {/* Transactions Feed */}
            <div className="divide-y divide-[#181624]">
              {/* Reference Transactions from Design */}
              {DEFAULT_TRANSACTIONS.map((tx) => (
                <div
                  key={tx.id}
                  className="flex items-center justify-between py-3.5 group hover:bg-[#12111d] px-2 rounded-xl transition-colors"
                >
                  <div className="flex items-center gap-3.5">
                    {/* Squircle Icon */}
                    <div
                      className={`flex h-10 w-10 items-center justify-center rounded-xl border ${
                        tx.iconType === "pending"
                          ? "border-[#78350f]/50 bg-[#241a08] text-[#fbbf24]"
                          : tx.iconType === "fund"
                          ? "border-[#581c87]/50 bg-[#1d122f] text-[#c084fc]"
                          : "border-[#134e4a]/50 bg-[#0a1e20] text-[#2dd4bf]"
                      }`}
                    >
                      {tx.iconType === "pending" ? (
                        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
                        </svg>
                      ) : tx.iconType === "fund" ? (
                        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                      ) : (
                        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                          <rect x="3" y="11" width="18" height="10" rx="2" />
                          <circle cx="12" cy="5" r="2" />
                          <path d="M12 7v4" />
                          <circle cx="8" cy="16" r="1.5" />
                          <circle cx="16" cy="16" r="1.5" />
                        </svg>
                      )}
                    </div>

                    <div>
                      <div className="text-xs font-semibold text-white">{tx.name}</div>
                      <div className="text-[11px] text-[#71717a] mt-0.5">{tx.subtitle}</div>
                    </div>
                  </div>

                  <div className="text-right">
                    <div
                      className={`text-xs font-bold ${
                        tx.status === "pending"
                          ? "text-[#f59e0b]"
                          : tx.status === "funded"
                          ? "text-[#34d399]"
                          : "text-[#2dd4bf]"
                      }`}
                    >
                      {tx.amount}
                    </div>
                    <div className="text-[10px] text-[#52525b] uppercase font-mono mt-0.5">{tx.rail}</div>
                  </div>
                </div>
              ))}

              {/* Live Real Purchases from Buyer Agent API */}
              {purchases.data && purchases.data.length > 0 && (
                <>
                  <div className="pt-3 pb-1 text-[10px] font-bold uppercase tracking-wider text-[#7c3aed]">
                    Live Maya Agent Purchases ({purchases.data.length})
                  </div>
                  {purchases.data.map((p) => {
                    const isExpanded = expandedId === p.purchase_id;
                    const isPaid = p.status === "PAID";
                    const isEscalated = p.status.includes("ESCALAT") || p.status.includes("REVIEW");

                    return (
                      <div key={p.purchase_id} className="py-2">
                        <button
                          onClick={() => setExpandedId(isExpanded ? null : p.purchase_id)}
                          className="flex w-full items-center justify-between text-left group hover:bg-[#12111d] p-2 rounded-xl transition-colors"
                        >
                          <div className="flex items-center gap-3.5">
                            <div
                              className={`flex h-10 w-10 items-center justify-center rounded-xl border ${
                                isPaid
                                  ? "border-[#134e4a]/50 bg-[#0a1e20] text-[#2dd4bf]"
                                  : isEscalated
                                  ? "border-[#78350f]/50 bg-[#241a08] text-[#fbbf24]"
                                  : "border-[#881337]/50 bg-[#1e0a12] text-[#f43f5e]"
                              }`}
                            >
                              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                                <path strokeLinecap="round" strokeLinejoin="round" d="M16 11V7a4 4 0 00-8 0v4M5 9h14l1 12H4L5 9z" />
                              </svg>
                            </div>

                            <div>
                              <div className="text-xs font-semibold text-white">
                                Maya Shopper → Kettle &amp; Crumb ({p.sku ?? "coffee"})
                              </div>
                              <div className="text-[11px] text-[#71717a] mt-0.5">
                                {isPaid
                                  ? `Auto-approved via ${p.funding_alias}`
                                  : isEscalated
                                  ? "Awaiting human review · Risk checks"
                                  : "Declined · PRP recovery attempted"}{" "}
                                · {new Date(p.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                              </div>
                            </div>
                          </div>

                          <div className="text-right">
                            <div
                              className={`text-xs font-bold ${
                                isPaid ? "text-[#2dd4bf]" : isEscalated ? "text-[#f59e0b]" : "text-[#f43f5e]"
                              }`}
                            >
                              -{fmt(p.amount_minor, p.currency_code)}
                            </div>
                            <div className="text-[10px] text-[#52525b] uppercase font-mono mt-0.5">
                              PayPal ({p.status})
                            </div>
                          </div>
                        </button>

                        {/* Expanded PRP Guard Decision Breakdown */}
                        {isExpanded && (
                          <div className="mt-2 ml-14 mr-2 rounded-xl border border-[#232035] bg-[#0f0e1a] p-3 text-xs space-y-3">
                            <PurchaseDetailsView purchaseId={p.purchase_id} amountMinor={p.amount_minor} currencyCode={p.currency_code} />
                          </div>
                        )}
                      </div>
                    );
                  })}
                </>
              )}
            </div>

            {/* Conversational Command Bar */}
            <div className="pt-4 border-t border-[#181624]">
              <div className="rounded-xl border border-[#232035] bg-[#0f0e1a] p-3">
                <div className="text-[11px] font-semibold text-white flex items-center justify-between mb-2">
                  <span>Ask Maya to buy something</span>
                  {health.data?.paused ? (
                    <span className="text-[10px] text-[#f59e0b] font-mono">Agent paused</span>
                  ) : (
                    <span className="text-[10px] text-[#2ebd7b] font-mono">Autonomous mode</span>
                  )}
                </div>

                <div className="flex gap-2">
                  <input
                    value={chatText}
                    onChange={(e) => setChatText(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleSendChat()}
                    placeholder="Order a 1 kg bag of the Ethiopian ($32.00)"
                    disabled={chatBusy}
                    className="flex-1 rounded-lg border border-[#232035] bg-[#090810] px-3 py-2 text-xs text-white placeholder-[#52525b] focus:border-[#7c3aed] focus:outline-none"
                  />
                  <button
                    disabled={chatBusy}
                    onClick={handleSendChat}
                    className="rounded-lg bg-[#7c3aed] px-4 py-2 text-xs font-semibold text-white hover:bg-[#6d28d9] transition-all disabled:opacity-50"
                  >
                    {chatBusy ? "Working…" : "Send"}
                  </button>
                </div>

                {chatReply && (
                  <div className="mt-2 text-xs text-[#a855f7] bg-[#1a1228] p-2.5 rounded-lg border border-[#3b1d60]">
                    {chatReply}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Right Column (4 cols): Active Agents & Spend Rules */}
        <div className="lg:col-span-4 space-y-6">
          {/* Card 1: Active Agents */}
          <div className="rounded-2xl border border-[#1b1928] bg-[#0c0b13] p-6 shadow-sm space-y-4">
            <h2 className="text-sm font-bold text-white">Active Agents</h2>

            <div className="space-y-3.5">
              <div className="flex items-center justify-between text-xs font-mono">
                <div className="flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full bg-[#10b981]" />
                  <span className="text-[#cbd5e1]">procurement-agent-v2</span>
                </div>
                <span className="text-[#71717a]">$500/day</span>
              </div>

              <div className="flex items-center justify-between text-xs font-mono">
                <div className="flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full bg-[#10b981]" />
                  <span className="text-[#cbd5e1]">insurance-claims-bot</span>
                </div>
                <span className="text-[#71717a]">$10k/txn</span>
              </div>

              <div className="flex items-center justify-between text-xs font-mono">
                <div className="flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full bg-[#10b981]" />
                  <span className="text-[#cbd5e1]">dev-agent-prod</span>
                </div>
                <span className="text-[#71717a]">$100/day</span>
              </div>

              <div className="flex items-center justify-between text-xs font-mono">
                <div className="flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full bg-[#f59e0b]" />
                  <span className="text-[#cbd5e1]">research-agent-01</span>
                </div>
                <span className="text-[#71717a]">$50/day</span>
              </div>

              {/* Real Maya Shopper row */}
              <div className="flex items-center justify-between text-xs font-mono pt-2 border-t border-[#181624]">
                <div className="flex items-center gap-2">
                  <span className={`h-2 w-2 rounded-full ${health.data?.paused ? "bg-[#f59e0b]" : "bg-[#10b981]"}`} />
                  <span className="text-[#a855f7] font-semibold">maya-shopper</span>
                </div>
                <span className="text-white">
                  {budget.data ? fmt(budget.data.limit_minor, budget.data.currency_code) : "$100"}/wk
                </span>
              </div>
            </div>

            <div className="pt-2">
              <button
                onClick={() => setAgentsModalOpen(true)}
                className="text-xs font-semibold text-[#8b5cf6] hover:text-[#a78bfa] transition-colors"
              >
                Manage agents →
              </button>
            </div>
          </div>

          {/* Card 2: Spend Rules */}
          <div className="rounded-2xl border border-[#1b1928] bg-[#0c0b13] p-6 shadow-sm space-y-4">
            <h2 className="text-sm font-bold text-white">Spend Rules</h2>

            <div className="space-y-3">
              <div className="flex items-center justify-between text-xs">
                <span className="text-[#71717a]">Auto-approve under</span>
                <span className="font-mono font-semibold text-white">
                  {activeMandate ? fmt(activeMandate.body.per_purchase_cap_minor, activeMandate.body.currency_code) : "$100"}
                </span>
              </div>

              <div className="flex items-center justify-between text-xs">
                <span className="text-[#71717a]">Human review over</span>
                <span className="font-mono font-semibold text-white">
                  {activeMandate ? fmt(activeMandate.body.per_purchase_cap_minor, activeMandate.body.currency_code) : "$500"}
                </span>
              </div>

              <div className="flex items-center justify-between text-xs">
                <span className="text-[#71717a]">Daily wallet limit</span>
                <span className="font-mono font-semibold text-white">$2,000</span>
              </div>

              <div className="flex items-center justify-between text-xs pt-2 border-t border-[#181624]">
                <span className="text-[#71717a]">Maya autonomous recoveries</span>
                <span className="font-mono text-[#2ebd7b]">Max 1× per order</span>
              </div>
            </div>

            {/* Quick Pause / Resume Action */}
            <div className="pt-2">
              <button
                onClick={async () => {
                  if (health.data?.paused) {
                    await buyer.resume();
                  } else {
                    await buyer.pause();
                  }
                  health.refresh();
                }}
                className={`w-full rounded-xl py-2 text-center text-xs font-semibold transition-all ${
                  health.data?.paused
                    ? "bg-[#241a08] text-[#fbbf24] border border-[#78350f]/50"
                    : "bg-[#181624] text-[#cbd5e1] hover:bg-[#201d30] border border-[#232035]"
                }`}
              >
                {health.data?.paused ? "Maya is Paused (tap to resume)" : "Pause Maya Shopping Agent"}
              </button>
            </div>

            <div>
              <button
                onClick={() => setRulesModalOpen(true)}
                className="text-xs font-semibold text-[#8b5cf6] hover:text-[#a78bfa] transition-colors"
              >
                Edit rules →
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* MODAL 1: Review Approvals */}
      {approvalsModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="w-full max-w-lg rounded-2xl border border-[#232035] bg-[#0c0b13] p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-[#181624] pb-3">
              <div className="flex items-center gap-2">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[#f59e0b] text-[10px] font-bold text-black">
                  !
                </span>
                <h3 className="text-sm font-bold text-white">Pending Approvals</h3>
              </div>
              <button onClick={() => setApprovalsModalOpen(false)} className="text-xs text-[#71717a] hover:text-white">
                ✕ Close
              </button>
            </div>

            <div className="space-y-3 max-h-[60vh] overflow-y-auto pr-1">
              {inbox.data && inbox.data.length > 0 ? (
                inbox.data.map((m) => (
                  <div key={m.msg_id} className="rounded-xl border border-[#232035] bg-[#12111d] p-3.5 space-y-2">
                    <div className="flex items-center justify-between text-[10px] font-mono">
                      <span className="text-[#a855f7] font-semibold">{m.kind}</span>
                      <span className="text-[#71717a]">{new Date(m.created_at).toLocaleTimeString()}</span>
                    </div>
                    <p className="text-xs text-[#cbd5e1] leading-relaxed">{m.text}</p>
                    <div className="flex items-center gap-3 pt-2">
                      {m.approve_url && (
                        <a
                          href={m.approve_url}
                          target="_blank"
                          rel="noreferrer"
                          className="rounded-lg bg-[#7c3aed] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#6d28d9] transition-all"
                        >
                          Approve on PayPal →
                        </a>
                      )}
                      <button
                        onClick={async () => {
                          await buyer.dismiss(m.msg_id);
                          inbox.refresh();
                        }}
                        className="text-xs text-[#71717a] hover:text-white"
                      >
                        Dismiss
                      </button>
                    </div>
                  </div>
                ))
              ) : (
                <div className="rounded-xl border border-[#232035] bg-[#12111d] p-4 text-center text-xs text-[#71717a]">
                  No pending escalations require human review. All purchases verified autonomously under PRP v0.1.
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* MODAL 2: Add Funds / Reset Mandate */}
      {addFundsModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="w-full max-w-md rounded-2xl border border-[#232035] bg-[#0c0b13] p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-[#181624] pb-3">
              <h3 className="text-sm font-bold text-white">Wallet &amp; Mandate Funds</h3>
              <button onClick={() => setAddFundsModalOpen(false)} className="text-xs text-[#71717a] hover:text-white">
                ✕ Close
              </button>
            </div>

            <p className="text-xs text-[#71717a] leading-relaxed">
              Top up or reset Maya&apos;s weekly budget pool. The buyer agent respects the human-approved mandate ceiling.
            </p>

            <div className="rounded-xl border border-[#232035] bg-[#12111d] p-3 text-xs space-y-2">
              <div className="flex justify-between">
                <span className="text-[#71717a]">Current Limit:</span>
                <span className="font-mono text-white font-semibold">
                  {budget.data ? fmt(budget.data.limit_minor, budget.data.currency_code) : "$100.00"}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#71717a]">Spent This Week:</span>
                <span className="font-mono text-[#2ebd7b]">
                  {budget.data ? fmt(budget.data.spent_minor, budget.data.currency_code) : "$0.00"}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#71717a]">Remaining:</span>
                <span className="font-mono text-[#a855f7] font-semibold">
                  {budget.data ? fmt(budget.data.remaining_minor, budget.data.currency_code) : "$100.00"}
                </span>
              </div>
            </div>

            <button
              onClick={async () => {
                await buyer.reset();
                budget.refresh();
                purchases.refresh();
                inbox.refresh();
                setAddFundsModalOpen(false);
              }}
              className="w-full rounded-xl bg-[#7c3aed] py-2.5 text-xs font-semibold text-white hover:bg-[#6d28d9] transition-all"
            >
              Reset Maya Spent Budget to $0.00 (Judge Baseline)
            </button>
          </div>
        </div>
      )}

      {/* MODAL 3: Spend Rules */}
      {rulesModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="w-full max-w-md rounded-2xl border border-[#232035] bg-[#0c0b13] p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-[#181624] pb-3">
              <h3 className="text-sm font-bold text-white">Spend Rules Configuration</h3>
              <button onClick={() => setRulesModalOpen(false)} className="text-xs text-[#71717a] hover:text-white">
                ✕ Close
              </button>
            </div>

            {activeMandate ? (
              <div className="space-y-2 text-xs">
                <div className="flex justify-between py-1 border-b border-[#181624]">
                  <span className="text-[#71717a]">Merchant Scope:</span>
                  <span className="font-mono text-white">{activeMandate.body.merchant_scope.join(", ")}</span>
                </div>
                <div className="flex justify-between py-1 border-b border-[#181624]">
                  <span className="text-[#71717a]">Allowed Categories:</span>
                  <span className="font-mono text-white">{activeMandate.body.allowed_categories.join(", ")}</span>
                </div>
                <div className="flex justify-between py-1 border-b border-[#181624]">
                  <span className="text-[#71717a]">Funding Priority:</span>
                  <span className="font-mono text-[#a855f7]">
                    {activeMandate.body.funding.map((f) => f.alias).join(" → ")}
                  </span>
                </div>
                <div className="flex justify-between py-1 border-b border-[#181624]">
                  <span className="text-[#71717a]">Escalate on:</span>
                  <span className="font-mono text-white">
                    {activeMandate.body.recovery.always_escalate_classes.join(", ")}
                  </span>
                </div>
              </div>
            ) : draftMandate ? (
              <div className="space-y-3">
                <p className="text-xs text-[#71717a]">Draft mandate pending your approval:</p>
                <button
                  onClick={async () => {
                    await buyer.activateMandate(draftMandate.mandate_id);
                    mandates.refresh();
                    setRulesModalOpen(false);
                  }}
                  className="w-full rounded-xl bg-[#7c3aed] py-2 text-xs font-semibold text-white"
                >
                  Approve Draft Mandate
                </button>
              </div>
            ) : (
              <p className="text-xs text-[#71717a]">Standard PRP v0.1 rules active.</p>
            )}
          </div>
        </div>
      )}

      {/* MODAL 4: Manage Agents */}
      {agentsModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="w-full max-w-md rounded-2xl border border-[#232035] bg-[#0c0b13] p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-[#181624] pb-3">
              <h3 className="text-sm font-bold text-white">Registered Agents</h3>
              <button onClick={() => setAgentsModalOpen(false)} className="text-xs text-[#71717a] hover:text-white">
                ✕ Close
              </button>
            </div>

            <div className="space-y-2 text-xs">
              <div className="rounded-xl border border-[#232035] bg-[#12111d] p-3 space-y-1">
                <div className="font-semibold text-white">Maya Buyer Agent</div>
                <div className="text-[11px] text-[#71717a]">Role: Autonomous Coffee &amp; Supplies Shopper</div>
                <div className="text-[10px] font-mono text-[#a855f7] truncate pt-1">
                  Key ID: {health.data?.agent_key_id ?? "agt_..."}
                </div>
                <div className="text-[10px] text-[#2ebd7b] font-mono">
                  Signing: {health.data?.signing_key} · PRP v0.1
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* MODAL 5: API Keys */}
      {keysModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="w-full max-w-md rounded-2xl border border-[#232035] bg-[#0c0b13] p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-[#181624] pb-3">
              <h3 className="text-sm font-bold text-white">Cryptographic API Keys</h3>
              <button onClick={() => setKeysModalOpen(false)} className="text-xs text-[#71717a] hover:text-white">
                ✕ Close
              </button>
            </div>

            <div className="space-y-2 text-xs">
              <div className="text-[11px] text-[#71717a]">Buyer Ed25519 Public Key:</div>
              <div className="font-mono text-[10px] bg-[#12111d] p-2.5 rounded-lg border border-[#232035] break-all text-white">
                {health.data?.agent_public_key ?? "ONpSTVHWB1atIX24vCoeLbNlUQVovsIWRc56tFOoKnA"}
              </div>
              <p className="text-[11px] text-[#71717a]">
                All recovery requests and mandate registrations are cryptographically signed.
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function PurchaseDetailsView({
  purchaseId,
  amountMinor,
  currencyCode,
}: {
  purchaseId: string;
  amountMinor: number;
  currencyCode: string;
}) {
  const detail = usePoll(() => buyer.purchase(purchaseId), 3000);

  if (!detail.data) {
    return <div className="text-xs text-[#71717a]">Loading PRP verification details…</div>;
  }

  const p = detail.data;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between border-b border-[#232035] pb-2 text-[11px]">
        <span className="font-mono text-[#71717a]">Intent: {p.intent_id ?? p.purchase_id}</span>
        <span className="text-[#a855f7] font-semibold">PRP v0.1 Verified</span>
      </div>

      {p.guard_decisions.length === 0 ? (
        <p className="text-xs text-[#71717a]">Paid on first try; no recovery offer needed.</p>
      ) : (
        p.guard_decisions.map((gd, i) => {
          const offer = p.offers.find((o) => o.offer_id === gd.offer_id) ?? p.offers[i];
          return (
            <div key={gd.gd_id} className="space-y-1.5">
              <Checklist gd={gd} title={`Recovery offer ${i + 1} · ${fmt(amountMinor, currencyCode)}`} />
              {offer?.scanner_flags && offer.scanner_flags.length > 0 && (
                <div className="rounded bg-[#2a1015] p-2 text-[10px] text-[#f43f5e] border border-[#50131d]">
                  Scanner flag: {offer.scanner_flags.join(", ")} (neutralized).
                </div>
              )}
            </div>
          );
        })
      )}
    </div>
  );
}
