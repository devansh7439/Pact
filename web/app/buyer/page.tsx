"use client";

import { useState } from "react";

import { Checklist } from "@/components/Checklist";
import { buyer, type InboxMessage, type MandateBody, type Purchase } from "@/lib/buyer";
import { fmt } from "@/lib/money";
import { usePoll } from "@/lib/usePoll";

const PERIOD = { DAY: "today", WEEK: "this week", MONTH: "this month" } as const;
const KIND_TONE: Record<InboxMessage["kind"], string> = {
  ESCALATION: "border-warn/50",
  RECEIPT: "border-ok/50",
  SECURITY: "border-bad/50",
  INFO: "border-line",
};

export default function BuyerPage() {
  const health = usePoll(buyer.health, 5000);
  const mandates = usePoll(buyer.mandates, 5000);
  const purchases = usePoll(buyer.purchases, 2500);
  const inbox = usePoll(buyer.inbox, 2500);
  const budget = usePoll(() => buyer.budget().catch(() => null), 2500);
  const active = mandates.data?.find((m) => m.status === "ACTIVE") ?? null;
  const draft = mandates.data?.find((m) => m.status === "DRAFT") ?? null;

  if (health.error) {
    return (
      <p className="rounded-md border border-bad/50 bg-surface p-4 text-sm">
        Can&apos;t reach the buyer agent ({health.error}). Start it with{" "}
        <code className="font-mono">uvicorn buyer_agent.app:app --port 8200</code>.
      </p>
    );
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
      <div className="min-w-0 space-y-6">
        <ChatBox
          onDone={() => {
            purchases.refresh();
            inbox.refresh();
            budget.refresh();
            mandates.refresh();
          }}
          hasMandate={!!active}
        />
        <section>
          <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-muted">Purchases</h2>
          {purchases.data?.length ? (
            <ul className="space-y-3">
              {purchases.data.map((p) => (
                <PurchaseRow key={p.purchase_id} p={p} />
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">No purchases yet.</p>
          )}
        </section>
      </div>

      <aside className="space-y-6">
        <PauseSwitch paused={!!health.data?.paused} onChange={health.refresh} />
        {budget.data && (
          <section className="rounded-lg border border-line bg-surface p-4">
            <h2 className="text-sm font-medium">Budget {PERIOD[budget.data.period as keyof typeof PERIOD]}</h2>
            <Meter spent={budget.data.spent_minor} limit={budget.data.limit_minor} />
            <p className="mt-1 text-sm text-muted">
              {fmt(budget.data.spent_minor, budget.data.currency_code)} spent ·{" "}
              {fmt(Math.max(budget.data.remaining_minor, 0), budget.data.currency_code)} left
            </p>
          </section>
        )}
        {active ? (
          <MandateCard m={active.body} status="ACTIVE" />
        ) : draft ? (
          <div className="space-y-2">
            <MandateCard m={draft.body} status="DRAFT" />
            <button
              className="w-full rounded-md bg-accent px-3 py-2 text-sm font-medium text-white"
              onClick={async () => {
                await buyer.activateMandate(draft.mandate_id);
                mandates.refresh();
                budget.refresh();
              }}
            >
              Approve this mandate
            </button>
          </div>
        ) : null}
        <section>
          <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-muted">Inbox</h2>
          {inbox.data?.length ? (
            <ul className="space-y-2">
              {inbox.data.map((m) => (
                <li key={m.msg_id} className={`rounded-md border bg-surface p-3 text-sm ${KIND_TONE[m.kind]}`}>
                  <p className="font-mono text-xs text-muted">{m.kind}</p>
                  <p className="mt-1">{m.text}</p>
                  <div className="mt-2 flex gap-3">
                    {m.approve_url && (
                      <a href={m.approve_url} target="_blank" rel="noreferrer" className="font-medium text-accent">
                        Approve on PayPal
                      </a>
                    )}
                    <button
                      className="text-muted hover:text-ink"
                      onClick={async () => {
                        await buyer.dismiss(m.msg_id);
                        inbox.refresh();
                      }}
                    >
                      Dismiss
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">Nothing needs your attention.</p>
          )}
        </section>
      </aside>
    </div>
  );
}

function ChatBox({ onDone, hasMandate }: { onDone: () => void; hasMandate: boolean }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [reply, setReply] = useState<string | null>(null);
  const placeholder = hasMandate
    ? "Order a 1 kg bag of the Ethiopian"
    : "Keep me stocked on beans, about $60 a week, max $50 per order";

  async function send() {
    if (!text.trim()) return;
    setBusy(true);
    setReply(null);
    try {
      if (hasMandate) {
        const r = await buyer.chat(text);
        setReply(r.reply);
      } else {
        const r = await buyer.draftMandate(text);
        setReply(`Drafted mandate ${r.mandate_id}. Review it on the right and approve it.`);
      }
      setText("");
      onDone();
    } catch (e) {
      setReply(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-lg border border-line bg-surface p-4">
      <label htmlFor="chat" className="text-sm font-medium">
        {hasMandate ? "Ask your agent to buy something" : "Tell your agent what it may spend"}
      </label>
      <div className="mt-2 flex gap-2">
        <input
          id="chat"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder={placeholder}
          className="min-w-0 flex-1 rounded-md border border-line bg-bg px-3 py-2 text-sm"
        />
        <button
          disabled={busy}
          onClick={send}
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {busy ? "Working…" : "Send"}
        </button>
      </div>
      {reply && <p className="mt-2 text-sm text-muted">{reply}</p>}
    </section>
  );
}

function PurchaseRow({ p }: { p: Purchase }) {
  const [open, setOpen] = useState(false);
  const detail = usePoll(() => (open ? buyer.purchase(p.purchase_id) : Promise.resolve(null)), 3000);
  const tone = p.status === "PAID" ? "text-ok" : p.status.includes("REJECT") ? "text-bad" : "text-warn";
  return (
    <li className="rounded-lg border border-line bg-surface">
      <button className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 p-3 text-left" onClick={() => setOpen(!open)}>
        <span className="font-medium">{p.sku ?? "item"}</span>
        <span>{fmt(p.amount_minor, p.currency_code)}</span>
        <span className={`text-sm ${tone}`}>
          {p.status}
          {p.outcome ? ` · ${p.outcome}` : ""}
        </span>
        <span className="ml-auto font-mono text-xs text-muted">{p.intent_id ?? p.purchase_id}</span>
      </button>
      {open && detail.data && (
        <div className="space-y-3 border-t border-line p-3">
          {detail.data.guard_decisions.length === 0 && (
            <p className="text-sm text-muted">Paid on the first try; no recovery offer.</p>
          )}
          {detail.data.guard_decisions.map((gd, i) => {
            const offer = detail.data!.offers.find((o) => o.offer_id === gd.offer_id) ?? detail.data!.offers[i];
            return (
              <div key={gd.gd_id} className="space-y-1">
                <Checklist gd={gd} title={`Recovery offer ${i + 1} · ${fmt(p.amount_minor, p.currency_code)}`} />
                {offer?.scanner_flags.length ? (
                  <p className="text-xs text-bad">
                    Offer text flagged ({offer.scanner_flags.join(", ")}). It was ignored and did not affect the
                    decision.
                  </p>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </li>
  );
}

function MandateCard({ m, status }: { m: MandateBody; status: string }) {
  const rows: [string, string][] = [
    ["Budget", `${fmt(m.budget.limit_minor, m.currency_code)} per ${m.budget.period.toLowerCase()}`],
    ["Per purchase", fmt(m.per_purchase_cap_minor, m.currency_code)],
    ["Merchants", m.merchant_scope.join(", ")],
    ["Categories", m.allowed_categories.join(", ") || "any"],
    ["Pay with", [...m.funding].sort((a, b) => a.priority - b.priority).map((f) => f.alias).join(" → ")],
    ["Auto-recover", m.recovery.allow_alternate_funding ? `yes, up to ${m.recovery.max_autonomous_recoveries_per_purchase}× per order` : "no"],
    ["Always ask me for", m.recovery.always_escalate_classes.map((c) => c.toLowerCase().replace(/_/g, " ")).join(", ")],
    ["Expires", new Date(m.expires_at).toLocaleDateString()],
  ];
  return (
    <section className="rounded-lg border border-line bg-surface p-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-medium">Mandate</h2>
        <span className={`font-mono text-xs ${status === "ACTIVE" ? "text-ok" : "text-warn"}`}>{status}</span>
      </div>
      <dl className="mt-2 space-y-1 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="flex gap-2">
            <dt className="w-32 shrink-0 text-muted">{k}</dt>
            <dd className="min-w-0 break-words">{v}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function Meter({ spent, limit }: { spent: number; limit: number }) {
  const pct = Math.min(100, Math.round((spent / Math.max(limit, 1)) * 100));
  return (
    <div
      className="mt-2 h-2 rounded-full bg-line"
      role="meter"
      aria-valuemin={0}
      aria-valuemax={limit}
      aria-valuenow={spent}
      aria-label="Budget used"
    >
      <div className={`h-2 rounded-full ${pct >= 90 ? "bg-bad" : "bg-accent"}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

function PauseSwitch({ paused, onChange }: { paused: boolean; onChange: () => void }) {
  return (
    <button
      onClick={async () => {
        await (paused ? buyer.resume() : buyer.pause());
        onChange();
      }}
      className={`w-full rounded-md border px-3 py-2 text-sm font-medium ${
        paused ? "border-warn bg-warn/10 text-warn" : "border-line bg-surface"
      }`}
    >
      {paused ? "Agent paused: tap to resume" : "Pause my agent"}
    </button>
  );
}
