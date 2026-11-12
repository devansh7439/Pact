"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { Checklist } from "@/components/Checklist";
import { DecisionInspector } from "@/components/DecisionInspector";
import { buyer, type PurchaseDetail } from "@/lib/buyer";
import { merchant, type Linked, type TimelineEntry } from "@/lib/merchant";
import { fmt } from "@/lib/money";
import { usePoll } from "@/lib/usePoll";

/** Linked view: merchant decision (left) · buyer guard (right) · one merged timeline. */
export default function LinkedRun() {
  const { intentId } = useParams<{ intentId: string }>();
  const linked = usePoll<Linked>(() => merchant.linked(intentId), 2000);
  // Use the merchant's server-side copy of the buyer half when it has one; otherwise ask the buyer directly.
  const buyerDirect = usePoll<PurchaseDetail | null>(
    () => (linked.data && linked.data.buyer === null ? buyer.byIntent(intentId).catch(() => null) : Promise.resolve(null)),
    2000,
  );
  const buyerSide = linked.data?.buyer ?? buyerDirect.data;
  const controls = usePoll(merchant.controls, 10000);

  if (linked.error && !linked.data) {
    return <p className="rounded-md border border-bad/50 bg-surface p-4 text-sm">Couldn&apos;t load {intentId}: {linked.error}</p>;
  }
  if (!linked.data) return <p className="text-sm text-muted">Loading {intentId}…</p>;

  const m = linked.data.merchant;
  const timeline = linked.data.timeline ?? mergeTimeline(m.timeline, buyerSide);
  const floor = controls.data ? Number(controls.data.ev_floor_minor) : undefined;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <Link href="/judge" className="text-sm text-muted hover:text-ink">
          ← Scenarios
        </Link>
        <h1 className="font-mono text-sm">{intentId}</h1>
        <span className="text-sm">{fmt(m.intent.amount_minor, m.intent.currency_code)}</span>
        <OutcomePill outcome={m.outcome?.outcome ?? m.intent.outcome ?? "PENDING"} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="min-w-0 space-y-3">
          <h2 className="text-sm font-medium uppercase tracking-wide text-muted">Merchant · Kettle &amp; Crumb</h2>
          {m.decisions.length === 0 && <p className="text-sm text-muted">No decision yet: the payment may have gone through first time.</p>}
          {m.decisions.map((d, i) => (
            <div key={d.decision_id} className="rounded-lg border border-line bg-surface p-4">
              <p className="mb-2 text-xs text-muted">Decision {i + 1}</p>
              <DecisionInspector d={d} floorMinor={floor} />
            </div>
          ))}
          {m.attempts.length > 0 && (
            <div className="rounded-lg border border-line bg-surface p-4">
              <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">PayPal attempts</h3>
              <ul className="space-y-1 font-mono text-xs">
                {m.attempts.map((a) => (
                  <li key={a.attempt_id} className="flex flex-wrap gap-x-3">
                    <span>{a.funding_alias ?? "payer approval"}</span>
                    <span className={a.status === "DECLINED" ? "text-bad" : a.status === "COMPLETED" ? "text-ok" : ""}>{a.status}</span>
                    {a.processor_code && <span>code {a.processor_code}</span>}
                    {a.issue && <span>{a.issue}</span>}
                    <span className="text-muted">order {a.paypal_order_id ?? "–"}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>

        <section className="min-w-0 space-y-3">
          <h2 className="text-sm font-medium uppercase tracking-wide text-muted">Buyer · Maya&apos;s agent</h2>
          {!buyerSide && <p className="text-sm text-muted">This intent has no buyer-agent record (human channel, or the buyer agent is unreachable).</p>}
          {buyerSide && (
            <>
              <p className="text-sm">
                Purchase <span className="font-mono text-xs">{buyerSide.purchase_id}</span> · {buyerSide.status}
                {buyerSide.failed_aliases.length > 0 && (
                  <span className="text-muted"> · failed so far: {buyerSide.failed_aliases.join(", ")}</span>
                )}
              </p>
              {buyerSide.guard_decisions.map((gd, i) => {
                const offer = buyerSide.offers.find((o) => o.offer_id === gd.offer_id) ?? buyerSide.offers[i];
                return (
                  <div key={gd.gd_id} className="space-y-1">
                    <Checklist gd={gd} title={`Offer ${i + 1}${offer ? ` · ${offer.offer_id}` : ""}`} />
                    {offer && !offer.signature_ok && (
                      <p className="text-xs text-bad">Signature check failed ({offer.signature_error}). The offer never reached the guard&apos;s other rules.</p>
                    )}
                    {offer?.scanner_flags.length ? (
                      <p className="text-xs text-bad">
                        Offer text flagged: {offer.scanner_flags.join(", ")}. Ignored; the decision never read it.
                      </p>
                    ) : null}
                  </div>
                );
              })}
              {buyerSide.guard_decisions.length === 0 && <p className="text-sm text-muted">No recovery offer reached the agent.</p>}
            </>
          )}
        </section>
      </div>

      <section>
        <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-muted">Timeline</h2>
        <ol className="space-y-1 text-sm">
          {timeline.map((t, i) => (
            <li key={i} className={`flex gap-3 ${t.side === "buyer" ? "pl-6 sm:pl-24" : ""}`}>
              <span className="w-20 shrink-0 font-mono text-xs text-muted">{new Date(t.at).toLocaleTimeString()}</span>
              <span className={`w-16 shrink-0 text-xs ${t.side === "buyer" ? "text-accent" : "text-muted"}`}>{t.side}</span>
              <span className="font-medium">{t.stage}</span>
              <span className="min-w-0 truncate text-muted">{summarise(t.detail)}</span>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

function mergeTimeline(merchantSide: TimelineEntry[], b: PurchaseDetail | null | undefined): TimelineEntry[] {
  const buyerSide: TimelineEntry[] = [];
  if (b) {
    buyerSide.push({ at: b.created_at, side: "buyer", stage: "PURCHASE", detail: { sku: b.sku, alias: b.funding_alias } });
    for (const o of b.offers)
      buyerSide.push({ at: o.received_at, side: "buyer", stage: "OFFER_RECEIVED",
        detail: { offer_id: o.offer_id, signature_ok: o.signature_ok, flags: o.scanner_flags } });
    for (const g of b.guard_decisions)
      buyerSide.push({ at: g.created_at, side: "buyer", stage: `GUARD_${g.result}`,
        detail: { rule: g.rule_fired, reason: g.reason, option: g.option_id, alias: g.alias } });
  }
  return [...merchantSide, ...buyerSide].sort((x, y) => Date.parse(x.at) - Date.parse(y.at));
}

function summarise(d: Record<string, unknown>): string {
  return Object.entries(d ?? {})
    .filter(([, v]) => v !== null && v !== undefined && !(Array.isArray(v) && v.length === 0) && typeof v !== "object")
    .slice(0, 5)
    .map(([k, v]) => `${k}=${String(v)}`)
    .join(" · ");
}

function OutcomePill({ outcome }: { outcome: string }) {
  const tone = outcome.startsWith("RECOVERED") || outcome === "ORGANIC" || outcome === "PAID"
    ? "bg-ok/10 text-ok" : outcome === "LOST" ? "bg-bad/10 text-bad" : "bg-warn/10 text-warn";
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${tone}`}>{outcome}</span>;
}
