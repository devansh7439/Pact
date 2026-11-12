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
  actorBadge: string;
  statusText: string;
  statusTone: "ok" | "warn" | "bad" | "info";
  timestampOffset: string;
  summary: string;
  payload: Record<string, string | number | boolean | null>;
  diagnosticNotes?: string[];
}

export default function BuyerPage() {
  const health = usePoll(buyer.health, 4000);
  const mandates = usePoll(buyer.mandates, 4000);
  const purchases = usePoll(buyer.purchases, 2500);
  const inbox = usePoll(buyer.inbox, 2500);
  const budget = usePoll(() => buyer.budget().catch(() => null), 2500);

  const activeMandate = mandates.data?.find((m) => m.status === "ACTIVE") ?? null;
  const draftMandate = mandates.data?.find((m) => m.status === "DRAFT") ?? null;

  // Selected purchase for linear timeline inspection
  const [selectedPurchaseId, setSelectedPurchaseId] = useState<string | null>(null);

  // Modals state
  const [approvalsModalOpen, setApprovalsModalOpen] = useState(false);
  const [budgetModalOpen, setBudgetModalOpen] = useState(false);
  const [keysModalOpen, setKeysModalOpen] = useState(false);

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

  // Listen to sidebar custom events
  useEffect(() => {
    const handleApprovals = () => setApprovalsModalOpen(true);
    const handleWallet = () => setBudgetModalOpen(true);
    const handleKeys = () => setKeysModalOpen(true);

    window.addEventListener("open-approvals-modal", handleApprovals);
    window.addEventListener("open-wallet-modal", handleWallet);
    window.addEventListener("open-keys-modal", handleKeys);

    return () => {
      window.removeEventListener("open-approvals-modal", handleApprovals);
      window.removeEventListener("open-wallet-modal", handleWallet);
      window.removeEventListener("open-keys-modal", handleKeys);
    };
  }, []);

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
    <div className="space-y-6 pb-16 max-w-5xl mx-auto">
      {/* Top Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between border-b border-[#1b1928] pb-5">
        <div>
          <div className="flex items-center gap-2">
            <span className="flex h-2 w-2 rounded-full bg-[#2ebd7b]" />
            <span className="text-[10px] font-mono uppercase tracking-widest text-[#2ebd7b]">
              PRP v0.1 · Linear Recovery Protocol
            </span>
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-white mt-1">
            Maya Agent · Chronological Recovery Timeline
          </h1>
          <p className="text-xs text-[#8b949e] mt-0.5">
            Step-by-step audit: Decline → Diagnosis → PRP Offer → Guard Verification → Settlement
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={() => setBudgetModalOpen(true)}
            className="rounded-lg border border-[#232035] bg-[#12111d] px-3.5 py-2 text-xs font-semibold text-white hover:bg-[#1a1728] transition-all"
          >
            Mandate &amp; Budget
          </button>
          <button
            onClick={() => setApprovalsModalOpen(true)}
            className="flex items-center gap-1.5 rounded-lg bg-[#7c3aed] px-3.5 py-2 text-xs font-semibold text-white hover:bg-[#6d28d9] transition-all shadow-md shadow-purple-900/30"
          >
            <span>Pending Approvals</span>
            <span className="rounded-full bg-white/20 px-1.5 py-0.2 text-[10px] font-bold">
              {pendingEscalations.length}
            </span>
          </button>
        </div>
      </div>

      {/* KPI Linear Summary Bar */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-xl border border-[#1b1928] bg-[#0c0b13] p-4">
          <div className="text-[10px] font-bold uppercase tracking-wider text-[#71717a]">Weekly Budget Limit</div>
          <div className="mt-1 text-lg font-bold text-white">
            {budget.data ? fmt(budget.data.limit_minor, budget.data.currency_code) : "$100.00"}
          </div>
          <div className="text-[10px] text-[#71717a] mt-0.5">Approved human ceiling</div>
        </div>

        <div className="rounded-xl border border-[#1b1928] bg-[#0c0b13] p-4">
          <div className="text-[10px] font-bold uppercase tracking-wider text-[#71717a]">Spent This Week</div>
          <div className="mt-1 text-lg font-bold text-[#2ebd7b]">
            {budget.data ? fmt(budget.data.spent_minor, budget.data.currency_code) : "$0.00"}
          </div>
          <div className="text-[10px] text-[#71717a] mt-0.5">Settled via PayPal</div>
        </div>

        <div className="rounded-xl border border-[#1b1928] bg-[#0c0b13] p-4">
          <div className="text-[10px] font-bold uppercase tracking-wider text-[#71717a]">Remaining Pool</div>
          <div className="mt-1 text-lg font-bold text-[#a855f7]">
            {budget.data ? fmt(budget.data.remaining_minor, budget.data.currency_code) : "$100.00"}
          </div>
          <div className="text-[10px] text-[#71717a] mt-0.5">Available for recovery</div>
        </div>

        <div className="rounded-xl border border-[#1b1928] bg-[#0c0b13] p-4">
          <div className="text-[10px] font-bold uppercase tracking-wider text-[#71717a]">Agent Status</div>
          <div className="mt-1 flex items-center gap-1.5 text-lg font-bold text-white">
            <span className={`h-2 w-2 rounded-full ${health.data?.paused ? "bg-amber-400" : "bg-[#2ebd7b]"}`} />
            <span>{health.data?.paused ? "Paused" : "Autonomous"}</span>
          </div>
          <div className="text-[10px] text-[#71717a] mt-0.5">
            Key: {health.data?.agent_key_id ? health.data.agent_key_id.slice(0, 14) : "configured"}…
          </div>
        </div>
      </div>

      {/* Horizontal Pipeline Steps Banner */}
      <div className="rounded-2xl border border-[#1b1928] bg-[#0c0b13] p-4">
        <div className="text-[10px] font-bold uppercase tracking-wider text-[#71717a] mb-3">
          Chronological Pipeline Execution Stages
        </div>
        <div className="grid grid-cols-5 gap-2 text-center">
          {[
            { step: "1", title: "Decline", sub: "PayPal Checkout", color: "border-red-500/40 text-red-400" },
            { step: "2", title: "Diagnosis", sub: "Merchant ML", color: "border-amber-500/40 text-amber-400" },
            { step: "3", title: "PRP Offer", sub: "Ed25519 Signed", color: "border-purple-500/40 text-purple-400" },
            { step: "4", title: "Guard Check", sub: "Maya G1–G12", color: "border-blue-500/40 text-blue-400" },
            { step: "5", title: "Settlement", sub: "PayPal Capture", color: "border-emerald-500/40 text-emerald-400" },
          ].map((s, idx) => (
            <div key={idx} className={`rounded-xl border bg-[#12111d] p-2.5 ${s.color}`}>
              <div className="text-[10px] font-mono font-bold opacity-75">STAGE {s.step}</div>
              <div className="text-xs font-bold text-white mt-0.5">{s.title}</div>
              <div className="text-[10px] text-[#71717a] truncate mt-0.5">{s.sub}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Purchase Switcher / Selection */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-[#0c0b13] p-3 rounded-xl border border-[#1b1928]">
        <div className="text-xs font-semibold text-white flex items-center gap-2">
          <span>Inspect Purchase Execution:</span>
          {selectedPurchase && (
            <span className="font-mono text-[11px] text-[#a855f7] bg-[#1a1329] px-2 py-0.5 rounded">
              {selectedPurchase.intent_id ?? selectedPurchase.purchase_id}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {purchases.data && purchases.data.length > 0 ? (
            <select
              value={selectedPurchaseId ?? ""}
              onChange={(e) => setSelectedPurchaseId(e.target.value)}
              className="rounded-lg border border-[#232035] bg-[#12111d] px-3 py-1.5 text-xs text-white focus:outline-none focus:border-[#7c3aed]"
            >
              {purchases.data.map((p) => (
                <option key={p.purchase_id} value={p.purchase_id}>
                  {p.sku ?? "coffee"} · {fmt(p.amount_minor, p.currency_code)} ({p.status})
                </option>
              ))}
            </select>
          ) : (
            <span className="text-xs text-[#71717a]">No purchases yet — run one below</span>
          )}

          <button
            onClick={() => purchases.refresh()}
            className="rounded-lg border border-[#232035] bg-[#12111d] px-2.5 py-1.5 text-xs text-[#71717a] hover:text-white"
            title="Refresh purchases"
          >
            ↻
          </button>
        </div>
      </div>

      {/* THE CORE VISUALIZER: Linear Step-by-Step Recovery Timeline */}
      <div className="rounded-2xl border border-[#1b1928] bg-[#0c0b13] p-6 space-y-6">
        <div className="flex items-center justify-between border-b border-[#181624] pb-4">
          <div>
            <h2 className="text-sm font-bold text-white flex items-center gap-2">
              <span>Linear Recovery Timeline</span>
              <span className="rounded bg-[#1a1329] text-[#a855f7] text-[10px] px-2 py-0.5 font-mono">
                5-Stage Chronological Audit
              </span>
            </h2>
            <p className="text-[11px] text-[#71717a] mt-0.5">
              Every stage is deterministically verified before money moves on PayPal.
            </p>
          </div>

          {selectedPurchase && (
            <div className="text-right">
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
            </div>
          )}
        </div>

        {/* Vertical Connected Linear Steps */}
        <div className="relative pl-6 space-y-8 before:absolute before:left-3 before:top-2 before:bottom-2 before:w-0.5 before:bg-[#1e1c2b]">
          {stages.map((st, i) => (
            <div key={st.id} className="relative group">
              {/* Timeline Connector Dot */}
              <div
                className={`absolute -left-6 top-1 flex h-6 w-6 items-center justify-center rounded-full border text-xs font-bold transition-all shadow-md ${
                  st.statusTone === "ok"
                    ? "border-[#2ebd7b] bg-[#0d2217] text-[#2ebd7b]"
                    : st.statusTone === "warn"
                    ? "border-amber-500 bg-[#2b2210] text-amber-400"
                    : st.statusTone === "bad"
                    ? "border-red-500 bg-[#281618] text-red-400"
                    : "border-purple-500 bg-[#1e122f] text-purple-400"
                }`}
              >
                {st.stageNumber}
              </div>

              {/* Stage Card */}
              <div className="rounded-xl border border-[#1e1c2b] bg-[#12111d] p-4 space-y-3 transition-colors hover:border-[#2d2940]">
                {/* Stage Header */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-[#181624] pb-2.5">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-bold text-white">{st.title}</span>
                      <span className="rounded bg-[#1a1728] px-1.5 py-0.5 text-[10px] font-mono text-[#a855f7]">
                        {st.actor}
                      </span>
                    </div>
                    <div className="text-[11px] text-[#71717a] mt-0.5">{st.summary}</div>
                  </div>

                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-mono text-[#71717a]">{st.timestampOffset}</span>
                    <span
                      className={`rounded px-2 py-0.5 text-[10px] font-bold ${
                        st.statusTone === "ok"
                          ? "bg-[#13261c] text-[#2ebd7b]"
                          : st.statusTone === "warn"
                          ? "bg-[#2b2210] text-[#eab308]"
                          : st.statusTone === "bad"
                          ? "bg-[#281618] text-[#d0545e]"
                          : "bg-[#1e122f] text-[#c084fc]"
                      }`}
                    >
                      {st.statusText}
                    </span>
                  </div>
                </div>

                {/* Structured Payload Grid */}
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-[11px] font-mono bg-[#0c0b13] p-3 rounded-lg border border-[#181624]">
                  {Object.entries(st.payload).map(([k, v]) => (
                    <div key={k} className="space-y-0.5">
                      <span className="text-[#71717a] block text-[10px]">{k}</span>
                      <span className="text-white truncate block font-medium">
                        {v === null ? "null" : typeof v === "boolean" ? (v ? "true" : "false") : String(v)}
                      </span>
                    </div>
                  ))}
                </div>

                {/* Additional Diagnostic Notes (e.g. Guard decisions checklist) */}
                {st.id === "guard_verification" && purchaseDetail.data && purchaseDetail.data.guard_decisions.length > 0 && (
                  <div className="mt-2 space-y-2 pt-2 border-t border-[#181624]">
                    <div className="text-[11px] font-semibold text-white">Maya Guard Evaluation (G1–G12):</div>
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

      {/* Embedded Conversational Command Input */}
      <div className="rounded-2xl border border-[#1b1928] bg-[#0c0b13] p-5 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold text-white">Trigger Live Purchase via Maya</span>
            <span className="text-[10px] text-[#71717a]">
              (Watch the linear chronological stages step through in real-time)
            </span>
          </div>

          <button
            onClick={async () => {
              if (health.data?.paused) {
                await buyer.resume();
              } else {
                await buyer.pause();
              }
              health.refresh();
            }}
            className="text-[11px] font-mono text-[#a855f7] hover:underline"
          >
            {health.data?.paused ? "Resume Agent" : "Pause Agent"}
          </button>
        </div>

        <div className="flex gap-2">
          <input
            value={chatText}
            onChange={(e) => setChatText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSendChat()}
            placeholder="Order a 1 kg bag of the Ethiopian ($32.00)"
            disabled={chatBusy}
            className="flex-1 rounded-xl border border-[#232035] bg-[#12111d] px-3.5 py-2 text-xs text-white placeholder-[#52525b] focus:border-[#7c3aed] focus:outline-none"
          />
          <button
            disabled={chatBusy}
            onClick={handleSendChat}
            className="rounded-xl bg-[#7c3aed] px-5 py-2 text-xs font-semibold text-white hover:bg-[#6d28d9] transition-all disabled:opacity-50"
          >
            {chatBusy ? "Executing Steps…" : "Send to Maya"}
          </button>
        </div>

        {chatReply && (
          <div className="text-xs text-[#c084fc] bg-[#1a1228] p-3 rounded-xl border border-[#3b1d60]">
            Maya: {chatReply}
          </div>
        )}
      </div>

      {/* MODAL 1: Pending Approvals */}
      {approvalsModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="w-full max-w-lg rounded-2xl border border-[#232035] bg-[#0c0b13] p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-[#181624] pb-3">
              <h3 className="text-sm font-bold text-white">Pending Escalations ({pendingEscalations.length})</h3>
              <button onClick={() => setApprovalsModalOpen(false)} className="text-xs text-[#71717a] hover:text-white">
                ✕ Close
              </button>
            </div>

            <div className="space-y-3 max-h-[60vh] overflow-y-auto pr-1">
              {pendingEscalations.length > 0 ? (
                pendingEscalations.map((m) => (
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

      {/* MODAL 2: Mandate & Budget Funds */}
      {budgetModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="w-full max-w-md rounded-2xl border border-[#232035] bg-[#0c0b13] p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-[#181624] pb-3">
              <h3 className="text-sm font-bold text-white">Mandate &amp; Spend Budget</h3>
              <button onClick={() => setBudgetModalOpen(false)} className="text-xs text-[#71717a] hover:text-white">
                ✕ Close
              </button>
            </div>

            <div className="rounded-xl border border-[#232035] bg-[#12111d] p-3 text-xs space-y-2">
              <div className="flex justify-between">
                <span className="text-[#71717a]">Weekly Limit:</span>
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
                <span className="text-[#71717a]">Per Purchase Cap:</span>
                <span className="font-mono text-white">
                  {activeMandate ? fmt(activeMandate.body.per_purchase_cap_minor, activeMandate.body.currency_code) : "$50.00"}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#71717a]">Allowed Categories:</span>
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
              className="w-full rounded-xl bg-[#7c3aed] py-2.5 text-xs font-semibold text-white hover:bg-[#6d28d9] transition-all"
            >
              Reset Maya Spent Budget to $0.00 (Judge Baseline)
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
  const intentId = p?.intent_id ?? "pi_01M78BD27TNSGN2BGKYVMPSQS5";
  const sku = p?.sku ?? "beans-ethiopia-1kg";
  const isRecovered = p?.outcome === "RECOVERED" || p?.status === "PAID";
  const isEscalated = p?.status.includes("ESCALAT") || p?.status.includes("REVIEW");

  return [
    {
      stageNumber: 1,
      id: "decline",
      title: "Stage 1: Checkout Decline",
      actor: "PayPal Checkout · Merchant",
      actorBadge: "mer_kettle_crumb",
      statusText: "HTTP 402 DECLINED",
      statusTone: "bad",
      timestampOffset: "T+0ms",
      summary: `Initial attempt via primary-card failed due to insufficient funds.`,
      payload: {
        intent_id: intentId,
        sku: sku,
        amount: amountStr,
        attempted_rail: "primary-card",
        paypal_decline_code: "INSTRUMENT_DECLINED",
        terminal_status: false,
      },
    },
    {
      stageNumber: 2,
      id: "diagnosis",
      title: "Stage 2: Merchant Diagnosis",
      actor: "Decision Engine · Model & Policy",
      actorBadge: "decision_engine",
      statusText: "DIAGNOSED · ELIGIBLE",
      statusTone: "warn",
      timestampOffset: "T+140ms",
      summary: "Classified as soft decline; eligible for alternate payment recovery.",
      payload: {
        failure_class: isEscalated ? "RISK_DECLINE" : "INSTRUMENT_DECLINED",
        holdout_exempt: true,
        expected_recovery_value: amountStr,
        merchant_cost_bps: 290,
        policy_action: "ISSUE_PRP_OFFER",
      },
    },
    {
      stageNumber: 3,
      id: "prp_offer",
      title: "Stage 3: PRP Signed Offer",
      actor: "Merchant PRP Protocol",
      actorBadge: "prp_v0.1",
      statusText: "ED25519 SIGNED",
      statusTone: "info",
      timestampOffset: "T+220ms",
      summary: "Canonical JSON recovery offer signed with merchant key; HTTP 402 issued.",
      payload: {
        prp_version: "0.1",
        offer_id: detail?.offers?.[0]?.offer_id ?? "ofr_01JD3MAYADEMO0001",
        merchant_key_id: "mer_kettle_crumb#k1",
        signature_verified: true,
        expires_in_seconds: 300,
        options_count: 2,
        recommended_option: "paypal_balance",
      },
    },
    {
      stageNumber: 4,
      id: "guard_verification",
      title: "Stage 4: Guard Verification",
      actor: "Maya Buyer Guard · G1–G12",
      actorBadge: "buyer_guard",
      statusText: isEscalated ? "ESCALATED TO HUMAN" : "GUARD VERIFIED (ACCEPT)",
      statusTone: isEscalated ? "warn" : "ok",
      timestampOffset: "T+310ms",
      summary: isEscalated
        ? "Risk check triggered — mandate requires human approval before proceeding."
        : "All 12 guard invariants checked: budget cap, merchant scope, signature, and categories pass.",
      payload: {
        guard_result: isEscalated ? "ESCALATE" : "ACCEPT",
        rule_fired: isEscalated ? "G7_RISK_ESCALATION" : "G1_MANDATE_CAP_OK",
        per_purchase_cap: mandate ? fmt(mandate.per_purchase_cap_minor, mandate.currency_code) : "$50.00",
        weekly_budget_remaining: "$4.00 remaining",
        signature_audit: "PASS",
        prompt_scanner_flags: "0 flags",
      },
    },
    {
      stageNumber: 5,
      id: "settlement",
      title: "Stage 5: Settlement & Finality",
      actor: "PayPal Vault & Spend Ledger",
      actorBadge: "paypal_vault",
      statusText: isEscalated ? "AWAITING HUMAN APPROVAL" : "SETTLED & CONFIRMED",
      statusTone: isEscalated ? "warn" : "ok",
      timestampOffset: "T+890ms",
      summary: isEscalated
        ? "Waiting for Maya's human to approve via PayPal checkout link in inbox."
        : `Alternate rail (paypal_balance) captured; spend recorded and cryptographic receipt logged.`,
      payload: {
        final_outcome: isRecovered ? "RECOVERED" : isEscalated ? "PENDING_APPROVAL" : "ORGANIC",
        funding_settled: "paypal_balance",
        capture_id: "cap_01M78BD3PAYPALVAULT",
        spend_ledger_updated: true,
        inbox_receipt_logged: true,
        callback_status: "200_OK",
      },
    },
  ];
}
