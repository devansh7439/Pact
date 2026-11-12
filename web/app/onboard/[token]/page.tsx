"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { buyer } from "@/lib/buyer";
import { merchant } from "@/lib/merchant";
import { fmt } from "@/lib/money";
import { usePoll } from "@/lib/usePoll";

/** Merchant-hosted onboarding: Maya sees the caps her agent asked for, saves PayPal, and approves. */
export default function Onboard() {
  const { token } = useParams<{ token: string }>();
  const ob = usePoll(() => merchant.onboarding(token), 4000);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  if (ob.error && !ob.data) return <p className="rounded-md border border-bad/50 bg-surface p-4 text-sm">{ob.error}</p>;
  if (!ob.data) return <p className="text-sm text-muted">Loading…</p>;

  const { mandate: m, merchant: mer } = ob.data;
  const cur = m.currency_code;
  const saved = new Map(ob.data.saved_funding.map((f) => [f.alias, f]));
  const active = ob.data.status === "ACTIVE";

  async function save(alias: string) {
    setBusy(alias);
    try {
      const r = await merchant.onboardVault(token, alias);
      window.location.href = r.approve_url; // PayPal approval, which returns to merchant /paypal/return
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
      setBusy(null);
    }
  }

  async function approve() {
    setBusy("approve");
    setMsg(null);
    try {
      const r = await merchant.onboardConfirm(token, m.principal.paypal_payer_id);
      // The merchant also sends the agent a signed registration.active callback; this is a fallback.
      await buyer.activateMandate(r.mandate_id).catch(() => undefined);
      setMsg(`Approved. Reference ${r.approval_ref}.`);
      ob.refresh();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  const rows: [string, string][] = [
    ["Spending budget", `${fmt(m.budget.limit_minor, cur)} per ${m.budget.period.toLowerCase()}`],
    ["Largest single purchase", fmt(m.per_purchase_cap_minor, cur)],
    ["Categories", m.allowed_categories.join(", ") || "any"],
    ["If a payment is declined",
      m.recovery.allow_alternate_funding
        ? `the agent may switch to another saved method, up to ${m.recovery.max_autonomous_recoveries_per_purchase}× per order`
        : "the agent always asks you"],
    ["Always ask you when", m.recovery.always_escalate_classes.map((c) => c.toLowerCase().replace(/_/g, " ")).join(", ")],
    ["Valid until", new Date(m.expires_at).toLocaleDateString()],
  ];

  return (
    <div className="mx-auto max-w-xl space-y-5">
      <div>
        <p className="text-sm text-muted">{mer.name}</p>
        <h1 className="text-xl font-semibold">Let {m.principal.display_name}&apos;s agent shop here</h1>
        <p className="mt-1 text-sm text-muted">
          Agent <span className="font-mono text-xs">{ob.data.agent_id}</span> asked to buy from {mer.name} within these
          limits. Nothing is charged until the agent places an order, and it can never go outside them.
        </p>
      </div>

      <table className="w-full text-sm">
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k} className="border-b border-line">
              <th scope="row" className="py-2 pr-3 text-left font-normal text-muted">{k}</th>
              <td className="py-2">{v}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <section className="space-y-2">
        <h2 className="text-sm font-medium">Payment methods the agent may use</h2>
        {[...m.funding].sort((a, b) => a.priority - b.priority).map((f) => {
          const s = saved.get(f.alias);
          return (
            <div key={f.alias} className="flex items-center gap-3 rounded-md border border-line bg-surface p-3 text-sm">
              <span className="font-medium">{f.alias}</span>
              <span className="text-muted">{f.kind === "PAYPAL_WALLET" ? "PayPal" : "Card"} · choice {f.priority}</span>
              {s ? (
                <span className="ml-auto text-ok">Saved with PayPal</span>
              ) : (
                <button
                  disabled={busy !== null || active}
                  onClick={() => save(f.alias)}
                  className="ml-auto rounded-md border border-accent px-3 py-1.5 font-medium text-accent disabled:opacity-50"
                >
                  {busy === f.alias ? "Opening PayPal…" : "Save with PayPal"}
                </button>
              )}
            </div>
          );
        })}
        <p className="text-xs text-muted">
          Saving with PayPal lets {mer.name} charge that method when your agent orders. These limits only control when
          the agent may ask, and you can pause the agent at any time.
        </p>
      </section>

      {active ? (
        <p className="rounded-md border border-ok/50 bg-surface p-3 text-sm text-ok">Approved. Your agent can shop here now.</p>
      ) : (
        <button
          disabled={busy !== null || saved.size === 0}
          onClick={approve}
          className="w-full rounded-md bg-accent px-4 py-2.5 font-medium text-white disabled:opacity-50"
        >
          {busy === "approve" ? "Approving…" : saved.size === 0 ? "Save a payment method first" : "Approve these limits"}
        </button>
      )}
      {msg && <p className="text-sm text-muted">{msg}</p>}
    </div>
  );
}
