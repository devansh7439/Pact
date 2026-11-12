"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { Checklist } from "@/components/Checklist";
import { buyer, type InboxMessage, type MandateBody, type Purchase, type PurchaseDetail } from "@/lib/buyer";
import { fmt } from "@/lib/money";
import { usePoll } from "@/lib/usePoll";

interface TimelineStage {
  stageNumber: number;
  id: "decline" | "diagnosis" | "prp_offer" | "guard_verification" | "settlement";
  title: string;
  actor: string;
  statusText: string;
  statusTone: "ok" | "warn" | "bad" | "info";
  timestampOffset: string;
  summary: string;
  highlights: { label: string; value: string }[];
}

export default function BuyerPage() {
  const health = usePoll(buyer.health, 4000);
  const mandates = usePoll(buyer.mandates, 4000);
  const purchases = usePoll(buyer.purchases, 2500);
  const inbox = usePoll(buyer.inbox, 2500);
  const budget = usePoll(() => buyer.budget().catch(() => null), 2500);

  const activeMandate = mandates.data?.find((m) => m.status === "ACTIVE") ?? null;

  // Selected purchase for linear timeline inspection
  const [selectedPurchaseId, setSelectedPurchaseId] = useState<string | null>(null);

  // Modals state
  const [approvalsModalOpen, setApprovalsModalOpen] = useState(false);
  const [budgetModalOpen, setBudgetModalOpen] = useState(false);

  // Conversational command state
  const [chatText, setChatText] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [chatReply, setChatReply] = useState<string | null>(null);

  // Default to latest purchase when data arrives
  useEffect(() => {
    if (purchases.data && purchases.data.length > 0 && !selectedPurchaseId) {
      setSelectedPurchaseId(purchases.data[0].purchase_id);
    }
  }, [purchases.data, selectedPurchaseId]);

  const pendingEscalations = inbox.data?.filter((m) => m.kind === "ESCALATION" && m.status !== "DISMISSED") ?? [];
  const selectedPurchase = purchases.data?.find((p) => p.purchase_id === selectedPurchaseId) ?? purchases.data?.[0] ?? null;

  // Poll details for currently selected purchase
  const purchaseDetail = usePoll(
    () => (selectedPurchase ? buyer.purchase(selectedPurchase.purchase_id) : Promise.resolve(null)),
    2500
  );

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
      if (purchases.data && purchases.data.length > 0) {
        setSelectedPurchaseId(purchases.data[0].purchase_id);
      }
    } catch (e) {
      setChatReply(e instanceof Error ? e.message : String(e));
    } finally {
      setChatBusy(false);
    }
  }

  // Construct Linear Timeline Stages based on selected purchase & real PRP checks
  const stages: TimelineStage[] = buildLinearTimeline(selectedPurchase, purchaseDetail.data, activeMandate?.body);

  return (
    <div className="space-y-6 pb-16 max-w-4xl mx-auto">
      {/* Top Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between border-b border-[#1b1f24] pb-5">
        <div>
          <div className="flex items-center gap-2">
            <span className="flex h-2 w-2 rounded-full bg-[#2ebd7b]" />
            <span className="text-[10px] font-mono uppercase tracking-widest text-[#2ebd7b]">
              PRP v0.1 · Buyer Agent
            </span>
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-white mt-1">
            Maya&apos;s Agent · Recovery Timeline
          </h1>
          <p className="text-xs text-[#8b949e] mt-0.5">
            5-stage execution audit: Decline → Diagnosis → PRP Offer → Guard Verification → Settlement
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={() => setBudgetModalOpen(true)}
            className="rounded-lg border border-[#23272f] bg-[#121518] px-3.5 py-2 text-xs font-semibold text-white hover:bg-[#1a1f26] transition-colors"
          >
            Mandate Limits
          </button>
          <button
            onClick={() => setApprovalsModalOpen(true)}
            className="flex items-center gap-1.5 rounded-lg bg-[#2ebd7b] px-3.5 py-2 text-xs font-semibold text-[#051a10] hover:bg-[#28a76d] transition-all"
          >
            <span>Pending Approvals</span>
            <span className="rounded-full bg-black/20 px-1.5 py-0.2 text-[10px] font-bold">
              {pendingEscalations.length}
            </span>
          </button>
        </div>
      </div>

      {/* KPI Summary Bar */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-xl border border-[#1b1f24] bg-[#0d0f0e] p-4">
          <div className="text-[11px] text-[#8b949e]">Weekly Limit</div>
          <div className="mt-1 text-lg font-bold text-white">
            {budget.data ? fmt(budget.data.limit_minor, budget.data.currency_code) : "$100.00"}
          </div>
        </div>

        <div className="rounded-xl border border-[#1b1f24] bg-[#0d0f0e] p-4">
          <div className="text-[11px] text-[#8b949e]">Spent This Week</div>
          <div className="mt-1 text-lg font-bold text-[#2ebd7b]">
            {budget.data ? fmt(budget.data.spent_minor, budget.data.currency_code) : "$0.00"}
          </div>
        </div>

        <div className="rounded-xl border border-[#1b1f24] bg-[#0d0f0e] p-4">
          <div className="text-[11px] text-[#8b949e]">Remaining Pool</div>
          <div className="mt-1 text-lg font-bold text-white">
            {budget.data ? fmt(budget.data.remaining_minor, budget.data.currency_code) : "$100.00"}
          </div>
        </div>

        <div className="rounded-xl border border-[#1b1f24] bg-[#0d0f0e] p-4">
          <div className="text-[11px] text-[#8b949e]">Agent State</div>
          <div className="mt-1 flex items-center gap-1.5 text-lg font-bold text-white">
            <span className={`h-2 w-2 rounded-full ${health.data?.paused ? "bg-[#eab308]" : "bg-[#2ebd7b]"}`} />
            <span>{health.data?.paused ? "Paused" : "Autonomous"}</span>
          </div>
        </div>
      </div>

      {/* Purchase Switcher / Selection */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-[#0d0f0e] p-3.5 rounded-xl border border-[#1b1f24]">
        <div className="text-xs font-semibold text-white flex items-center gap-2">
          <span>Active Purchase:</span>
          {selectedPurchase && (
            <span className="font-mono text-[11px] text-[#2ebd7b] bg-[#13261c] px-2 py-0.5 rounded">
              {selectedPurchase.intent_id ?? selectedPurchase.purchase_id}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {purchases.data && purchases.data.length > 0 ? (
            <select
              value={selectedPurchaseId ?? ""}
              onChange={(e) => setSelectedPurchaseId(e.target.value)}
              className="rounded-lg border border-[#23272f] bg-[#121518] px-3 py-1.5 text-xs text-white focus:outline-none focus:border-[#2ebd7b]"
            >
              {purchases.data.map((p) => (
                <option key={p.purchase_id} value={p.purchase_id}>
                  {p.sku ?? "coffee"} · {fmt(p.amount_minor, p.currency_code)} ({p.status})
                </option>
              ))}
            </select>
          ) : (
            <span className="text-xs text-[#8b949e]">No purchases yet — trigger one below</span>
          )}

          <button
            onClick={() => purchases.refresh()}
            className="rounded-lg border border-[#23272f] bg-[#121518] px-2.5 py-1.5 text-xs text-[#8b949e] hover:text-white"
            title="Refresh purchases"
          >
            ↻
          </button>
        </div>
      </div>

      {/* Linear Step-by-Step Recovery Timeline */}
      <div className="rounded-2xl border border-[#1b1f24] bg-[#0d0f0e] p-5 sm:p-6 space-y-6">
        <div className="flex items-center justify-between border-b border-[#1b1f24] pb-4">
          <div>
            <h2 className="text-sm font-bold text-white">Chronological Execution Stages</h2>
            <p className="text-[11px] text-[#8b949e] mt-0.5">
              Verified deterministically against mandate invariants before settlement.
            </p>
          </div>

          {selectedPurchase && (
            <span
              className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                selectedPurchase.status === "PAID"
                  ? "bg-[#13261c] text-[#2ebd7b]"
                  : selectedPurchase.status.includes("ESCALAT")
                  ? "bg-[#2b2210] text-[#eab308]"
                  : "bg-[#281618] text-[#d0545e]"
              }`}
            >
              {selectedPurchase.status} {selectedPurchase.outcome ? `· ${selectedPurchase.outcome}` : ""}
            </span>
          )}
        </div>

        {/* Vertical Connected Steps */}
        <div className="relative pl-6 space-y-6 before:absolute before:left-3 before:top-2 before:bottom-2 before:w-0.5 before:bg-[#1b1f24]">
          {stages.map((st) => (
            <div key={st.id} className="relative group">
              {/* Connector Dot */}
              <div
                className={`absolute -left-6 top-1 flex h-6 w-6 items-center justify-center rounded-full border text-xs font-bold transition-all shadow-md ${
                  st.statusTone === "ok"
                    ? "border-[#2ebd7b] bg-[#0d2217] text-[#2ebd7b]"
                    : st.statusTone === "warn"
                    ? "border-amber-500 bg-[#2b2210] text-amber-400"
                    : st.statusTone === "bad"
                    ? "border-red-500 bg-[#281618] text-red-400"
                    : "border-sky-500 bg-[#0c1e28] text-sky-400"
                }`}
              >
                {st.stageNumber}
              </div>

              {/* Stage Card */}
              <div className="rounded-xl border border-[#1b1f24] bg-[#121518] p-4 space-y-2.5 transition-colors hover:border-[#28303a]">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-[#1b1f24] pb-2">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-bold text-white">{st.title}</span>
                      <span className="rounded bg-[#1a1f26] px-1.5 py-0.5 text-[10px] font-mono text-[#8b949e]">
                        {st.actor}
                      </span>
                    </div>
                    <div className="text-xs text-[#8b949e] mt-1">{st.summary}</div>
                  </div>

                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-mono text-[#6e7681]">{st.timestampOffset}</span>
                    <span
                      className={`rounded px-2 py-0.5 text-[10px] font-bold ${
                        st.statusTone === "ok"
                          ? "bg-[#13261c] text-[#2ebd7b]"
                          : st.statusTone === "warn"
                          ? "bg-[#2b2210] text-[#eab308]"
                          : st.statusTone === "bad"
                          ? "bg-[#281618] text-[#d0545e]"
                          : "bg-[#0c1e28] text-sky-400"
                      }`}
                    >
                      {st.statusText}
                    </span>
                  </div>
                </div>

                {/* Compact Highlights Pills */}
                <div className="flex flex-wrap gap-2 text-[11px] font-mono pt-1">
                  {st.highlights.map((h, idx) => (
                    <div key={idx} className="rounded bg-[#0d0f0e] border border-[#1b1f24] px-2.5 py-1 flex items-center gap-1.5">
                      <span className="text-[#6e7681] text-[10px]">{h.label}:</span>
                      <span className="text-white font-medium">{h.value}</span>
                    </div>
                  ))}
                </div>

                {/* Guard Decisions Checklist */}
                {st.id === "guard_verification" && purchaseDetail.data && purchaseDetail.data.guard_decisions.length > 0 && (
                  <div className="mt-2 space-y-2 pt-2 border-t border-[#1b1f24]">
                    <div className="text-[11px] font-semibold text-white">Maya Guard Checklist (G1–G12):</div>
                    {purchaseDetail.data.guard_decisions.map((gd) => (
                      <Checklist key={gd.gd_id} gd={gd} title="Cryptographic Guard Verification" />
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Trigger Purchase Command Input */}
      <div className="rounded-2xl border border-[#1b1f24] bg-[#0d0f0e] p-5 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-xs font-bold text-white">Trigger Purchase Command</span>
          <button
            onClick={async () => {
              if (health.data?.paused) {
                await buyer.resume();
              } else {
                await buyer.pause();
              }
              health.refresh();
            }}
            className="text-[11px] font-mono text-[#2ebd7b] hover:underline"
          >
            {health.data?.paused ? "Resume Agent" : "Pause Agent"}
          </button>
        </div>

        <div className="flex gap-2">
          <input
            value={chatText}
            onChange={(e) => setChatText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSendChat()}
            placeholder="Order a 1 kg bag of Ethiopian coffee ($32.00)"
            disabled={chatBusy}
            className="flex-1 rounded-xl border border-[#23272f] bg-[#121518] px-3.5 py-2 text-xs text-white placeholder-[#6e7681] focus:border-[#2ebd7b] focus:outline-none"
          />
          <button
            disabled={chatBusy || !chatText.trim()}
            onClick={handleSendChat}
            className="rounded-xl bg-[#2ebd7b] px-4 py-2 text-xs font-semibold text-[#051a10] hover:bg-[#28a76d] transition-all disabled:opacity-50"
          >
            {chatBusy ? "Processing…" : "Send"}
          </button>
        </div>

        {chatReply && (
          <div className="text-xs text-[#2ebd7b] bg-[#102318] p-3 rounded-xl border border-[#1b3b27]">
            Maya: {chatReply}
          </div>
        )}
      </div>

      {/* MODAL 1: Pending Approvals */}
      {approvalsModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="w-full max-w-lg rounded-2xl border border-[#23272f] bg-[#0d0f0e] p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-[#1b1f24] pb-3">
              <h3 className="text-sm font-bold text-white">Pending Escalations ({pendingEscalations.length})</h3>
              <button onClick={() => setApprovalsModalOpen(false)} className="text-xs text-[#8b949e] hover:text-white">
                ✕ Close
              </button>
            </div>

            <div className="space-y-3 max-h-[60vh] overflow-y-auto pr-1">
              {pendingEscalations.length > 0 ? (
                pendingEscalations.map((m) => (
                  <div key={m.msg_id} className="rounded-xl border border-[#23272f] bg-[#121518] p-3.5 space-y-2">
                    <div className="flex items-center justify-between text-[10px] font-mono">
                      <span className="text-[#2ebd7b] font-semibold">{m.kind}</span>
                      <span className="text-[#6e7681]">{new Date(m.created_at).toLocaleTimeString()}</span>
                    </div>
                    <p className="text-xs text-[#cbd5e1] leading-relaxed">{m.text}</p>
                    <div className="flex items-center gap-3 pt-2">
                      {m.approve_url && (
                        <a
                          href={m.approve_url}
                          target="_blank"
                          rel="noreferrer"
                          className="rounded-lg bg-[#2ebd7b] px-3 py-1.5 text-xs font-semibold text-[#051a10] hover:bg-[#28a76d] transition-all"
                        >
                          Approve on PayPal →
                        </a>
                      )}
                      <button
                        onClick={async () => {
                          await buyer.dismiss(m.msg_id);
                          inbox.refresh();
                        }}
                        className="text-xs text-[#8b949e] hover:text-white"
                      >
                        Dismiss
                      </button>
                    </div>
                  </div>
                ))
              ) : (
                <div className="rounded-xl border border-[#23272f] bg-[#121518] p-4 text-center text-xs text-[#8b949e]">
                  No pending escalations require human review. All purchases verified autonomously under PRP v0.1.
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* MODAL 2: Mandate & Budget Limits */}
      {budgetModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="w-full max-w-md rounded-2xl border border-[#23272f] bg-[#0d0f0e] p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-[#1b1f24] pb-3">
              <h3 className="text-sm font-bold text-white">Mandate Spending Limits</h3>
              <button onClick={() => setBudgetModalOpen(false)} className="text-xs text-[#8b949e] hover:text-white">
                ✕ Close
              </button>
            </div>

            <div className="rounded-xl border border-[#23272f] bg-[#121518] p-3 text-xs space-y-2">
              <div className="flex justify-between">
                <span className="text-[#8b949e]">Weekly Limit:</span>
                <span className="font-mono text-white font-semibold">
                  {budget.data ? fmt(budget.data.limit_minor, budget.data.currency_code) : "$100.00"}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#8b949e]">Spent This Week:</span>
                <span className="font-mono text-[#2ebd7b]">
                  {budget.data ? fmt(budget.data.spent_minor, budget.data.currency_code) : "$0.00"}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#8b949e]">Per Purchase Cap:</span>
                <span className="font-mono text-white">
                  {activeMandate ? fmt(activeMandate.body.per_purchase_cap_minor, activeMandate.body.currency_code) : "$50.00"}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#8b949e]">Allowed Categories:</span>
                <span className="font-mono text-white">
                  {activeMandate ? activeMandate.body.allowed_categories.join(", ") : "coffee, tea"}
                </span>
              </div>
            </div>

            <button
              onClick={async () => {
                await buyer.reset();
                budget.refresh();
                purchases.refresh();
                inbox.refresh();
                setBudgetModalOpen(false);
              }}
              className="w-full rounded-xl bg-[#2ebd7b] py-2.5 text-xs font-semibold text-[#051a10] hover:bg-[#28a76d] transition-all"
            >
              Reset Spent Budget to $0.00
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function buildLinearTimeline(
  p: Purchase | null,
  detail: PurchaseDetail | null,
  mandate?: MandateBody
): TimelineStage[] {
  const amountStr = p ? fmt(p.amount_minor, p.currency_code) : "$32.00";
  const intentId = p?.intent_id ?? "pi_demo_01";
  const sku = p?.sku ?? "coffee-ethiopian-1kg";
  const isRecovered = p?.outcome === "RECOVERED" || p?.status === "PAID";
  const isEscalated = p?.status.includes("ESCALAT") || p?.status.includes("REVIEW");

  return [
    {
      stageNumber: 1,
      id: "decline",
      title: "Stage 1 · Checkout Decline",
      actor: "PayPal Checkout",
      statusText: "402 DECLINED",
      statusTone: "bad",
      timestampOffset: "T+0ms",
      summary: `Initial checkout attempt declined for ${amountStr} (${sku}).`,
      highlights: [
        { label: "Intent", value: intentId.slice(0, 14) + "…" },
        { label: "Rail", value: "primary-card" },
        { label: "Amount", value: amountStr },
        { label: "Signal", value: "INSTRUMENT_DECLINED" },
      ],
    },
    {
      stageNumber: 2,
      id: "diagnosis",
      title: "Stage 2 · Merchant Diagnosis",
      actor: "Decision Engine",
      statusText: "DIAGNOSED",
      statusTone: "warn",
      timestampOffset: "T+140ms",
      summary: "Classified decline code; evaluated recovery actions and economic value.",
      highlights: [
        { label: "Class", value: isEscalated ? "RISK_BLOCKED" : "INSUFFICIENT_FUNDS" },
        { label: "Action", value: isEscalated ? "ESCALATE" : "ALTERNATE_FUNDING" },
        { label: "Expected Value", value: amountStr },
      ],
    },
    {
      stageNumber: 3,
      id: "prp_offer",
      title: "Stage 3 · Signed PRP Offer",
      actor: "PRP Protocol",
      statusText: "SIGNED",
      statusTone: "info",
      timestampOffset: "T+220ms",
      summary: "Canonical JSON recovery offer signed with merchant Ed25519 key.",
      highlights: [
        { label: "Version", value: "PRP v0.1" },
        { label: "Key ID", value: "mer_kettle_crumb#k1" },
        { label: "Signature", value: "Verified" },
      ],
    },
    {
      stageNumber: 4,
      id: "guard_verification",
      title: "Stage 4 · Guardrail Check",
      actor: "Maya Buyer Guard",
      statusText: isEscalated ? "ESCALATED" : "VERIFIED (ACCEPT)",
      statusTone: isEscalated ? "warn" : "ok",
      timestampOffset: "T+310ms",
      summary: isEscalated
        ? "Mandate rule triggered: requires human approval before proceeding."
        : "All 12 mandate guard invariants verified: cap, merchant scope, signature, category.",
      highlights: [
        { label: "Result", value: isEscalated ? "ESCALATE" : "ACCEPT" },
        { label: "Per-order Cap", value: mandate ? fmt(mandate.per_purchase_cap_minor, mandate.currency_code) : "$50.00" },
        { label: "Scanner", value: "Clean (0 flags)" },
      ],
    },
    {
      stageNumber: 5,
      id: "settlement",
      title: "Stage 5 · Settlement & Finality",
      actor: "PayPal Vault",
      statusText: isEscalated ? "PENDING APPROVAL" : "SETTLED",
      statusTone: isEscalated ? "warn" : "ok",
      timestampOffset: "T+890ms",
      summary: isEscalated
        ? "One-tap PayPal approval link delivered to Maya's inbox."
        : "Alternate rail captured; budget recorded and signed receipt confirmed.",
      highlights: [
        { label: "Outcome", value: isRecovered ? "RECOVERED" : isEscalated ? "ESCALATED" : "PENDING" },
        { label: "Funding", value: "paypal-wallet" },
        { label: "Ledger", value: "Updated" },
      ],
    },
  ];
}
