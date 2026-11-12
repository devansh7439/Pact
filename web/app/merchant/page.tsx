"use client";

import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";

import type { ColDef, ValueFormatterParams } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { useMemo, useState } from "react";

import { DecisionInspector, ProvenanceBadge } from "@/components/DecisionInspector";
import { merchant, type Controls, type LedgerRow, type ModelMetrics, type ProvenanceMetrics } from "@/lib/merchant";
import { fmt } from "@/lib/money";
import { usePoll } from "@/lib/usePoll";

const moneyFmt = (p: ValueFormatterParams<LedgerRow>) =>
  p.value === null || p.value === undefined ? "–" : fmt(p.value as number, p.data?.currency_code ?? "USD");

export default function MerchantConsole() {
  const health = usePoll(merchant.health, 5000);
  const ledger = usePoll(merchant.ledger, 3000);
  const metrics = usePoll(merchant.metrics, 5000);
  const controls = usePoll(merchant.controls, 5000);
  const queue = usePoll(merchant.reviewQueue, 3000);
  const security = usePoll(merchant.security, 5000);
  const model = usePoll(merchant.model, 30000);
  const [selected, setSelected] = useState<string | null>(null);

  const cols = useMemo<ColDef<LedgerRow>[]>(
    () => [
      { field: "created_at", headerName: "When", sort: "desc", width: 170,
        valueFormatter: (p) => (p.value ? new Date(p.value as string).toLocaleString() : "") },
      { field: "intent_id", headerName: "Intent", width: 200, cellClass: "font-mono text-xs" },
      { field: "channel", headerName: "Channel", width: 100, filter: true },
      { field: "amount_minor", headerName: "Amount", width: 110, type: "rightAligned", valueFormatter: moneyFmt },
      { field: "failure_class", headerName: "Failure", width: 170, filter: true },
      { field: "chosen_action", headerName: "Action", width: 190, filter: true },
      { field: "nev_minor", headerName: "NEV", width: 100, type: "rightAligned", valueFormatter: moneyFmt },
      { field: "held_out", headerName: "Held out", width: 100, valueFormatter: (p) => (p.value ? "yes" : "") },
      { field: "outcome", headerName: "Outcome", width: 170, filter: true },
      { field: "provenance", headerName: "Provenance", width: 120, filter: true },
      { field: "mode", headerName: "Mode", width: 130 },
    ],
    [],
  );

  if (health.error) {
    return (
      <p className="rounded-md border border-bad/50 bg-surface p-4 text-sm">
        Can&apos;t reach merchant-api ({health.error}). Start it with{" "}
        <code className="font-mono">uvicorn merchant.app:app --port 8100</code>.
      </p>
    );
  }

  const floor = controls.data ? Number(controls.data.ev_floor_minor) : undefined;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <h1 className="text-lg font-semibold">Kettle &amp; Crumb · recovery console</h1>
        {health.data && (
          <span className="font-mono text-xs text-muted">
            PayPal {health.data.paypal} · LLM {health.data.llm} · key {health.data.merchant_key_id}
          </span>
        )}
      </div>

      {controls.data && <ControlsBar c={controls.data} onChange={controls.refresh} />}

      <section className="grid gap-4 md:grid-cols-3">
        {metrics.data &&
          (Object.entries(metrics.data.by_provenance) as [string, ProvenanceMetrics][]).map(([prov, m]) => (
            <MetricsCard key={prov} prov={prov} m={m} />
          ))}
      </section>
      {metrics.data && <p className="-mt-3 text-xs text-muted">{metrics.data.note}</p>}

      <section>
        <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-muted">Decision ledger</h2>
        <div className="ag-theme-quartz-auto-dark h-[420px] w-full">
          <AgGridReact<LedgerRow>
            rowData={ledger.data ?? []}
            columnDefs={cols}
            getRowId={(p) => p.data.decision_id}
            onRowClicked={(e) => e.data && setSelected(e.data.decision_id)}
            rowSelection="single"
            animateRows={false}
            defaultColDef={{ resizable: true, sortable: true }}
            overlayNoRowsTemplate="No decisions yet. Run a scenario from Judge mode."
          />
        </div>
      </section>

      <div className="grid gap-6 md:grid-cols-2">
        <section>
          <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-muted">Review queue</h2>
          {queue.data?.length ? (
            <ul className="space-y-2">
              {queue.data.map((r) => (
                <li key={r.decision_id} className="flex flex-wrap items-center gap-3 rounded-md border border-line bg-surface p-3 text-sm">
                  <button className="font-mono text-xs text-accent" onClick={() => setSelected(r.decision_id)}>
                    {r.decision_id}
                  </button>
                  <span>{r.chosen_action}</span>
                  <span>{fmt(r.amount_minor)}</span>
                  <span className="ml-auto flex gap-2">
                    <button
                      className="rounded bg-accent px-2 py-1 text-xs font-medium text-white"
                      onClick={async () => {
                        await merchant.review(r.decision_id, true);
                        queue.refresh();
                        ledger.refresh();
                      }}
                    >
                      Approve
                    </button>
                    <button
                      className="rounded border border-line px-2 py-1 text-xs"
                      onClick={async () => {
                        await merchant.review(r.decision_id, false);
                        queue.refresh();
                      }}
                    >
                      Reject
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">Nothing waiting for review.</p>
          )}
        </section>
        <section>
          <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-muted">Security events</h2>
          {security.data?.length ? (
            <ul className="max-h-64 space-y-1 overflow-auto text-xs">
              {security.data.map((e) => (
                <li key={e.id} className="rounded border border-bad/40 bg-surface p-2">
                  <span className="font-medium text-bad">{e.kind}</span>
                  <span className="ml-2 text-muted">{new Date(e.created_at).toLocaleTimeString()}</span>
                  <pre className="mt-1 whitespace-pre-wrap break-all font-mono">{JSON.stringify(e.detail)}</pre>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">None.</p>
          )}
        </section>
      </div>

      {model.data?.available && <ModelCard m={model.data} />}

      {selected && <Drawer id={selected} floor={floor} onClose={() => setSelected(null)} />}
    </div>
  );
}

function Drawer({ id, floor, onClose }: { id: string; floor?: number; onClose: () => void }) {
  const d = usePoll(() => merchant.decision(id), 4000);
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-ink/30" onClick={onClose} role="presentation">
      <aside
        role="dialog"
        aria-label="Decision inspector"
        className="h-full w-full max-w-2xl overflow-y-auto border-l border-line bg-surface p-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-medium">Decision inspector</h2>
          <button onClick={onClose} className="text-sm text-muted hover:text-ink">
            Close
          </button>
        </div>
        {d.error && <p className="text-sm text-bad">{d.error}</p>}
        {d.data && <DecisionInspector d={d.data} floorMinor={floor} />}
      </aside>
    </div>
  );
}

function MetricsCard({ prov, m }: { prov: string; m: ProvenanceMetrics }) {
  const h = m.holdout;
  const p = (x: number) => `${(x * 100).toFixed(1)}%`;
  return (
    <div className="rounded-lg border border-line bg-surface p-4 text-sm">
      <div className="flex items-center justify-between">
        <ProvenanceBadge p={prov} />
        <span className="text-xs text-muted">{m.intents_with_failures} failed intents</span>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-y-1">
        <dt className="text-muted">Caused by Pact</dt>
        <dd className="text-right font-medium">{fmt(m.caused_minor)}</dd>
        <dt className="text-muted">Organic</dt>
        <dd className="text-right">{fmt(m.organic_minor)}</dd>
        <dt className="text-muted">Lost</dt>
        <dd className="text-right">{fmt(m.lost_minor)}</dd>
      </dl>
      <div className="mt-3 border-t border-line pt-2 text-xs">
        <p className="text-muted">Live holdout (Wilson 95%)</p>
        <p>
          acted {p(h.acted.rate)} [{p(h.acted.low)}–{p(h.acted.high)}] n={h.acted.n}
        </p>
        <p>
          held out {p(h.held_out.rate)} [{p(h.held_out.low)}–{p(h.held_out.high)}] n={h.held_out.n}
        </p>
        <p className="font-medium">{h.enough_data && h.lift !== null ? `lift ${p(h.lift)}` : h.message}</p>
      </div>
    </div>
  );
}

function ModelCard({ m }: { m: ModelMetrics }) {
  const n = (x?: number) => (x === undefined ? "–" : x.toFixed(3));
  return (
    <section className="rounded-lg border border-line bg-surface p-4 text-sm">
      <div className="flex items-center gap-2">
        <h2 className="text-sm font-medium uppercase tracking-wide text-muted">Recovery model</h2>
        <ProvenanceBadge p={m.provenance} />
      </div>
      <p className="mt-2">
        ROC AUC {n(m.roc_auc)} <span className="text-muted">(oracle ceiling {n(m.oracle_auc)})</span> · Brier {n(m.brier)}{" "}
        <span className="text-muted">(baseline {n(m.brier_baseline)})</span>
      </p>
      {m.calibration_bins?.length ? (
        <div className="mt-2 overflow-x-auto">
          <table className="min-w-[24rem] text-xs">
            <thead className="text-left text-muted">
              <tr>
                <th className="pr-4 font-normal">Bin</th>
                <th className="pr-4 text-right font-normal">n</th>
                <th className="pr-4 text-right font-normal">Predicted</th>
                <th className="text-right font-normal">Observed</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {m.calibration_bins.map((b) => (
                <tr key={b.range}>
                  <td className="pr-4">{b.range}</td>
                  <td className="pr-4 text-right">{b.n}</td>
                  <td className="pr-4 text-right">{n(b.predicted)}</td>
                  <td className="text-right">{n(b.observed)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <p className="mt-2 text-xs text-muted">Trained and scored on simulated data only; simulated events never reach PayPal or the LLM.</p>
    </section>
  );
}

function ControlsBar({ c, onChange }: { c: Controls; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  async function set(changes: Partial<Record<keyof Controls, string>>) {
    setBusy(true);
    try {
      await merchant.setControls(changes);
      onChange();
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-surface p-3 text-sm">
      <label className="flex items-center gap-2">
        Mode
        <select
          disabled={busy}
          value={c.mode}
          onChange={(e) => set({ mode: e.target.value })}
          className="rounded border border-line bg-bg px-2 py-1"
        >
          <option value="review_first">review first</option>
          <option value="autonomous">autonomous</option>
        </select>
      </label>
      <span className="text-muted">
        floor {fmt(Number(c.ev_floor_minor))} · ceiling {fmt(Number(c.autonomy_ceiling_minor))} · holdout{" "}
        {(Number(c.holdout_rate) * 100).toFixed(0)}% · max attempts {c.max_recovery_attempts}
      </span>
      <button
        disabled={busy}
        onClick={() => set({ kill_switch: c.kill_switch === "on" ? "off" : "on" })}
        className={`ml-auto rounded-md px-3 py-1.5 font-medium ${
          c.kill_switch === "on" ? "bg-bad text-white" : "border border-bad/60 text-bad"
        }`}
      >
        {c.kill_switch === "on" ? "Kill switch ON: nothing executes" : "Kill switch"}
      </button>
    </section>
  );
}
