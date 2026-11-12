import { OptionTable } from "@/components/OptionTable";
import type { Decision } from "@/lib/merchant";
import { fmt } from "@/lib/money";

export function ProvenanceBadge({ p }: { p: string }) {
  const tone = p === "sandbox" ? "border-ok/60 text-ok" : p === "fixture" ? "border-warn/60 text-warn" : "border-line text-muted";
  return <span className={`rounded border px-1.5 py-0.5 font-mono text-[11px] uppercase ${tone}`}>{p}</span>;
}

/** Decision inspector: stage trace, per-option table, offers as signed, outcome. */
export function DecisionInspector({ d, floorMinor }: { d: Decision; floorMinor?: number }) {
  const cur = d.intent?.currency_code ?? "USD";
  const t = d.stage_trace;
  return (
    <div className="space-y-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-muted">{d.decision_id}</span>
        {d.intent && <ProvenanceBadge p={d.intent.provenance} />}
        {d.held_out ? <span className="rounded bg-warn/10 px-1.5 py-0.5 text-xs text-warn">held out: no action</span> : null}
        {d.review_status && <span className="rounded bg-line px-1.5 py-0.5 text-xs">review {d.review_status}</span>}
      </div>

      <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1">
        {d.intent && (
          <>
            <dt className="text-muted">Amount</dt>
            <dd>
              {fmt(d.intent.amount_minor, cur)} · {d.intent.channel} channel
            </dd>
          </>
        )}
        <dt className="text-muted">Failure</dt>
        <dd>
          {t.failure_class} <span className="text-muted">(diagnosed by {t.diagnosed_by})</span>
        </dd>
        <dt className="text-muted">Decision</dt>
        <dd>
          <span className="font-medium">{d.chosen_action}</span>
          {d.nev_minor !== null && <> · NEV {fmt(d.nev_minor, cur)}</>} ·{" "}
          <span className="font-mono text-xs">{t.rule_id}</span>
        </dd>
        <dt className="text-muted">Why</dt>
        <dd>{t.rationale}</dd>
        {t.constraints.length > 0 && (
          <>
            <dt className="text-muted">Constraints</dt>
            <dd className="font-mono text-xs">{t.constraints.join(" · ")}</dd>
          </>
        )}
        {t.execution_blocked_by && (
          <>
            <dt className="text-muted">Blocked by</dt>
            <dd className="text-bad">{t.execution_blocked_by}</dd>
          </>
        )}
        {d.outcome && (
          <>
            <dt className="text-muted">Outcome</dt>
            <dd>
              {d.outcome.outcome} · {fmt(d.outcome.recovered_minor, cur)} via {d.outcome.source}
            </dd>
          </>
        )}
      </dl>

      <section>
        <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">Per-option table</h3>
        <OptionTable options={d.options} currency={cur} floorMinor={floorMinor} />
        <p className="mt-1 text-xs text-muted">
          Base propensity {(t.base_propensity * 100).toFixed(1)}% from {t.propensity_source} (label:{" "}
          {d.labels.probabilities}).
        </p>
      </section>

      {d.offers.length > 0 && (
        <section>
          <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">Offer as signed</h3>
          {d.offers.map((o) => (
            <details key={o.offer_id} className="rounded border border-line">
              <summary className="cursor-pointer px-2 py-1 font-mono text-xs">
                {o.offer_id} · {o.status}
                {o.accepted_option_id ? ` · accepted ${o.accepted_option_id}` : ""}
              </summary>
              <pre className="max-h-72 overflow-auto bg-bg p-2 font-mono text-[11px] leading-snug">
                {JSON.stringify(o.body, null, 2)}
              </pre>
            </details>
          ))}
        </section>
      )}
    </div>
  );
}
