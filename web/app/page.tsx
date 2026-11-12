"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useRef, useState } from "react";

import { DecisionInspector } from "@/components/DecisionInspector";
import { merchant, type Decision, type LedgerRow, type ProvenanceMetrics } from "@/lib/merchant";
import { fmt } from "@/lib/money";
import { usePoll } from "@/lib/usePoll";

interface KpiCardProps {
  icon: React.ReactNode;
  label: string;
  tag: string;
  value: React.ReactNode;
  badgeText: string;
  badgeTone?: "ok" | "bad" | "neutral";
}

function KpiCard({ icon, label, tag, value, badgeText, badgeTone = "ok" }: KpiCardProps) {
  const badgeClasses =
    badgeTone === "bad"
      ? "bg-[#281618] text-[#d0545e]"
      : badgeTone === "neutral"
      ? "bg-[#161a22] text-[#8b949e]"
      : "bg-[#13261c] text-[#2ebd7b]";

  return (
    <div className="rounded-2xl border border-[#1b1f24] bg-[#0d0f0e] p-5 transition-all hover:border-[#28303a]">
      <div className="flex items-center justify-between text-xs text-[#8b949e]">
        <div className="flex items-center gap-2">
          {icon}
          <span className="font-medium text-white">{label}</span>
        </div>
        <span className="text-[10px] uppercase font-mono text-[#6e7681]">{tag}</span>
      </div>
      <div className="mt-3 flex items-baseline gap-2.5">
        <span className="text-2xl font-bold tracking-tight text-white xl:text-[26px]">
          {value}
        </span>
        <span className={`flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[11px] font-semibold ${badgeClasses}`}>
          {badgeText}
        </span>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const health = usePoll(merchant.health, 5000);
  const ledger = usePoll(merchant.ledger, 3000);
  const metrics = usePoll(merchant.metrics, 5000);
  const controls = usePoll(merchant.controls, 5000);
  const queue = usePoll(merchant.reviewQueue, 3000);

  const [selectedDecisionId, setSelectedDecisionId] = useState<string | null>(null);
  const [selectedDecision, setSelectedDecision] = useState<Decision | null>(null);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [loadingDecision, setLoadingDecision] = useState(false);
  const [selectedProvenance, setSelectedProvenance] = useState<string>("all");
  const [runningS1, setRunningS1] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const activeReqRef = useRef<string | null>(null);

  const isKillSwitchOn = controls.data?.kill_switch === "on";

  // Sum real metrics across provenances
  const totals = useMemo(() => {
    if (!metrics.data?.by_provenance) {
      return { grossMinor: 0, causedMinor: 0, organicMinor: 0, lostMinor: 0, intents: 0 };
    }
    let gross = 0;
    let caused = 0;
    let organic = 0;
    let lost = 0;
    let intents = 0;
    for (const m of Object.values(metrics.data.by_provenance) as ProvenanceMetrics[]) {
      gross += m.gross_minor;
      caused += m.caused_minor;
      organic += m.organic_minor;
      lost += m.lost_minor;
      intents += m.intents_with_failures;
    }
    return { grossMinor: gross, causedMinor: caused, organicMinor: organic, lostMinor: lost, intents };
  }, [metrics.data]);

  // Filter ledger rows by selected provenance
  const filteredLedger = useMemo(() => {
    if (!ledger.data) return [];
    if (selectedProvenance === "all") return ledger.data;
    return ledger.data.filter((r) => r.provenance === selectedProvenance);
  }, [ledger.data, selectedProvenance]);

  // Aggregate failure classes from filtered ledger data
  const failureBreakdown = useMemo(() => {
    const counts: Record<string, { count: number; totalMinor: number }> = {};
    for (const r of filteredLedger) {
      const fc = r.failure_class || "UNKNOWN";
      if (!counts[fc]) counts[fc] = { count: 0, totalMinor: 0 };
      counts[fc].count += 1;
      counts[fc].totalMinor += r.amount_minor;
    }
    return Object.entries(counts).sort((a, b) => b[1].count - a[1].count);
  }, [filteredLedger]);

  // Aggregate chosen actions from filtered ledger data
  const actionBreakdown = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const r of filteredLedger) {
      const act = r.chosen_action || "DROP";
      counts[act] = (counts[act] || 0) + 1;
    }
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [filteredLedger]);

  // Load decision detail for the inspector modal without race conditions
  const openDecision = async (id: string) => {
    activeReqRef.current = id;
    setSelectedDecisionId(id);
    setSelectedDecision(null);
    setDecisionError(null);
    setLoadingDecision(true);
    try {
      const d = await merchant.decision(id);
      if (activeReqRef.current === id) {
        setSelectedDecision(d);
      }
    } catch (e) {
      if (activeReqRef.current === id) {
        setDecisionError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      if (activeReqRef.current === id) {
        setLoadingDecision(false);
      }
    }
  };

  // Run Scenario S1 directly from Quick Actions
  const runScenarioS1 = async () => {
    setRunningS1(true);
    setActionError(null);
    try {
      const res = await merchant.runScenario("S1");
      if (res.intent_id) {
        router.push(`/judge/run/${res.intent_id}`);
      } else {
        const detail = res.result?.detail ?? res.result?.status ?? "no checkout occurred";
        const hint = detail === "over_budget" || detail === "OUTSIDE_MANDATE"
          ? " (Weekly budget exhausted: press Reset in Judge Mode)"
          : "";
        setActionError(`Scenario S1: ${detail}${hint}`);
      }
    } catch (e) {
      setActionError(`Scenario S1: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setRunningS1(false);
    }
  };

  // Export real ledger rows to CSV using Blob and proper quoting
  const exportLedgerCSV = () => {
    if (!ledger.data || ledger.data.length === 0) return;
    const headers = [
      "Decision ID",
      "Created At",
      "Intent ID",
      "Channel",
      "Amount Minor",
      "Currency",
      "Failure Class",
      "Chosen Action",
      "NEV Minor",
      "Held Out",
      "Outcome",
    ];

    const escapeCsv = (val: unknown) => {
      if (val === null || val === undefined) return '""';
      const str = String(val).replace(/"/g, '""');
      return `"${str}"`;
    };

    const lines = [
      headers.map(escapeCsv).join(","),
      ...ledger.data.map((r) =>
        [
          r.decision_id,
          r.created_at,
          r.intent_id,
          r.channel,
          r.amount_minor,
          r.currency_code,
          r.failure_class,
          r.chosen_action,
          r.nev_minor ?? "",
          r.held_out ? "1" : "0",
          r.outcome ?? "",
        ]
          .map(escapeCsv)
          .join(",")
      ),
    ];

    const blob = new Blob([lines.join("\r\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `pact_decisions_ledger_${Date.now()}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const holdoutProvKey = selectedProvenance === "all" ? "fixture" : selectedProvenance;
  const activeProvenanceData =
    metrics.data?.by_provenance?.[holdoutProvKey as keyof typeof metrics.data.by_provenance];

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-2xl font-bold tracking-tight text-white md:text-[28px]">
              Kettle &amp; Crumb
            </h1>
            <span className="rounded bg-[#1a231e] px-2 py-0.5 text-xs font-mono text-[#2ebd7b]">
              PayPal {health.data?.paypal ?? "–"}
            </span>
          </div>
          <p className="mt-1 text-xs text-[#8b949e] md:text-sm">
            Autonomous decline diagnosis &amp; signed recovery offers (PRP v0.1)
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          {controls.data && (
            <button
              onClick={async () => {
                await merchant.setControls({
                  kill_switch: isKillSwitchOn ? "off" : "on",
                });
                controls.refresh();
              }}
              className={`flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-xs font-semibold transition-all ${
                isKillSwitchOn
                  ? "bg-[#d0545e] text-white shadow-lg shadow-red-900/30"
                  : "border border-[#2ebd7b]/40 bg-[#0d0f0e] text-[#2ebd7b] hover:bg-[#13261c]"
              }`}
            >
              <span className={`h-2 w-2 rounded-full ${isKillSwitchOn ? "bg-white" : "bg-[#2ebd7b]"}`} />
              <span>{isKillSwitchOn ? "Kill switch ON (execution blocked)" : "Kill switch OFF (normal)"}</span>
            </button>
          )}

          {ledger.data && ledger.data.length > 0 && (
            <button
              onClick={exportLedgerCSV}
              className="flex items-center gap-1.5 rounded-lg border border-[#23272f] bg-[#121518] px-3.5 py-2 text-xs font-medium text-white transition-colors hover:bg-[#1c2128]"
            >
              <span>Export ledger</span>
              <svg className="h-3.5 w-3.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M19 14l-7 7m0 0l-7-7m7 7V3" />
              </svg>
            </button>
          )}

          <Link
            href="/judge"
            className="flex items-center gap-1.5 rounded-lg bg-[#2ebd7b] px-4 py-2 text-xs font-semibold text-[#051a10] shadow-sm transition-all hover:bg-[#28a76d]"
          >
            Judge scenarios (S1–S6) →
          </Link>
        </div>
      </div>

      {actionError && (
        <div className="rounded-xl border border-[#d0545e]/40 bg-[#281618] p-3 text-xs text-[#d0545e] flex items-center justify-between">
          <span>{actionError}</span>
          <button onClick={() => setActionError(null)} className="text-white hover:underline text-[11px]">
            Dismiss
          </button>
        </div>
      )}

      {/* Engine Controls Bar */}
      {controls.data && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[#1b1f24] bg-[#0d0f0e] px-4 py-3 text-xs">
          <div className="flex flex-wrap items-center gap-4 text-[#8b949e]">
            <div className="flex items-center gap-2">
              <span className="text-white font-medium">Policy mode:</span>
              <select
                value={controls.data.mode}
                onChange={async (e) => {
                  await merchant.setControls({ mode: e.target.value });
                  controls.refresh();
                }}
                className="rounded-md border border-[#23272f] bg-[#121518] px-2 py-1 text-xs font-semibold text-[#2ebd7b] focus:outline-none"
              >
                <option value="autonomous">autonomous</option>
                <option value="review_first">review first</option>
              </select>
            </div>
            <span>•</span>
            <div>
              Floor: <span className="text-white font-mono">{fmt(Number(controls.data.ev_floor_minor))}</span>
            </div>
            <span>•</span>
            <div>
              Ceiling: <span className="text-white font-mono">{fmt(Number(controls.data.autonomy_ceiling_minor))}</span>
            </div>
            <span>•</span>
            <div>
              Holdout: <span className="text-white font-mono">{(Number(controls.data.holdout_rate) * 100).toFixed(0)}%</span>
            </div>
          </div>
          <div className="font-mono text-[11px] text-[#6e7681]">
            Max recovery attempts: {controls.data.max_recovery_attempts}
          </div>
        </div>
      )}

      {/* KPI Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          icon={
            <svg className="h-4 w-4 text-[#2ebd7b]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          }
          label="Gross Recovered"
          tag="Live"
          value={fmt(totals.grossMinor)}
          badgeText="Caused + Organic"
        />

        <KpiCard
          icon={
            <svg className="h-4 w-4 text-[#2ebd7b]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
            </svg>
          }
          label="Caused Recovery"
          tag="Lift"
          value={fmt(totals.causedMinor)}
          badgeText="Engine Lift"
        />

        <KpiCard
          icon={
            <svg className="h-4 w-4 text-[#8b949e]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          }
          label="Decisions Handled"
          tag="Audit"
          value={ledger.data?.length ?? 0}
          badgeText="Policy Gated"
        />

        <KpiCard
          icon={
            <svg className="h-4 w-4 text-[#8b949e]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          }
          label="Review Queue"
          tag="Human Gate"
          value={queue.data?.length ?? 0}
          badgeText={(queue.data?.length ?? 0) > 0 ? "Action required" : "Queue clear"}
          badgeTone={(queue.data?.length ?? 0) > 0 ? "bad" : "ok"}
        />
      </div>

      {/* Analytics Breakdown Grid */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-12">
        <div className="rounded-2xl border border-[#1b1f24] bg-[#0d0f0e] p-6 lg:col-span-8">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-sm font-semibold text-white">Decline Diagnosis &amp; Policy Actions</h2>
              <p className="mt-0.5 text-xs text-[#8b949e]">
                Breakdown of declines and evaluated actions ({filteredLedger.length} orders shown)
              </p>
            </div>

            {/* Provenance Selector Filter */}
            <div className="flex items-center gap-1 rounded-lg border border-[#23272f] bg-[#121518] p-1 text-xs">
              {(["all", "fixture", "sandbox", "simulated"] as const).map((prov) => (
                <button
                  key={prov}
                  onClick={() => setSelectedProvenance(prov)}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium uppercase transition-colors ${
                    selectedProvenance === prov
                      ? "bg-[#1f2620] text-[#2ebd7b]"
                      : "text-[#8b949e] hover:text-white"
                  }`}
                >
                  {prov}
                </button>
              ))}
            </div>
          </div>

          {/* Failure Class Breakdown */}
          <div className="mt-6 space-y-4">
            <div className="text-xs font-medium uppercase tracking-wider text-[#6e7681]">
              Diagnosed Failure Classes ({failureBreakdown.length} classes in {selectedProvenance} view)
            </div>

            {failureBreakdown.length > 0 ? (
              <div className="space-y-3">
                {failureBreakdown.map(([fc, stat]) => {
                  const pct = Math.round((stat.count / (filteredLedger.length || 1)) * 100);
                  return (
                    <div key={fc} className="space-y-1.5">
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-mono text-white">{fc}</span>
                        <div className="flex items-center gap-3">
                          <span className="text-[#8b949e]">{fmt(stat.totalMinor)}</span>
                          <span className="font-semibold text-[#2ebd7b]">{stat.count} orders ({pct}%)</span>
                        </div>
                      </div>
                      <div className="h-2 w-full overflow-hidden rounded-full bg-[#161a22]">
                        <div
                          style={{ width: `${pct}%` }}
                          className="h-full rounded-full bg-gradient-to-r from-[#2ebd7b] to-[#a8b858]"
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="py-4 text-xs text-[#8b949e]">
                No declines recorded under {selectedProvenance} yet.
              </p>
            )}
          </div>

          {/* Actions Executed */}
          <div className="mt-6 border-t border-[#1b1f24] pt-5">
            <div className="text-xs font-medium uppercase tracking-wider text-[#6e7681]">
              Engine Decisions Executed
            </div>
            {actionBreakdown.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {actionBreakdown.map(([act, count]) => (
                  <div
                    key={act}
                    className="flex items-center gap-2 rounded-lg border border-[#23272f] bg-[#121518] px-3 py-1.5 text-xs"
                  >
                    <span className="font-mono text-white">{act}</span>
                    <span className="rounded bg-[#13261c] px-1.5 py-0.5 font-semibold text-[#2ebd7b]">
                      {count}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-2 text-xs text-[#8b949e]">No actions executed in this slice.</p>
            )}
          </div>

          {/* Holdout Statistics */}
          {activeProvenanceData && (
            <div className="mt-6 rounded-xl border border-[#1b1f24] bg-[#121518] p-4 text-xs">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-white uppercase">{holdoutProvKey} Holdout Lift</span>
                <span className="text-[#6e7681]">Wilson 95% Interval</span>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
                <div>
                  <span className="text-[#6e7681] block">Intents:</span>
                  <span className="font-semibold text-white">{activeProvenanceData.intents_with_failures}</span>
                </div>
                <div>
                  <span className="text-[#6e7681] block">Caused:</span>
                  <span className="font-semibold text-[#2ebd7b]">{fmt(activeProvenanceData.caused_minor)}</span>
                </div>
                <div>
                  <span className="text-[#6e7681] block">Organic:</span>
                  <span className="font-semibold text-white">{fmt(activeProvenanceData.organic_minor)}</span>
                </div>
                <div>
                  <span className="text-[#6e7681] block">Lift:</span>
                  <span className="font-semibold text-[#2ebd7b]">
                    {activeProvenanceData.holdout.enough_data && activeProvenanceData.holdout.lift !== null
                      ? `${(activeProvenanceData.holdout.lift * 100).toFixed(1)}%`
                      : activeProvenanceData.holdout.message}
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Right Column: Review Queue & Quick Actions */}
        <div className="flex flex-col gap-5 lg:col-span-4">
          <div className="flex flex-col justify-between rounded-2xl border border-[#1b1f24] bg-[#0d0f0e] p-5">
            <div>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 text-xs text-[#8b949e]">
                  <svg className="h-3.5 w-3.5 text-[#8b949e]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                  </svg>
                  <span className="font-medium text-white">Review Queue</span>
                </div>
                <span className="text-[10px] text-[#6e7681]">Human Gate</span>
              </div>

              {queue.data && queue.data.length > 0 ? (
                <div className="mt-3 space-y-2">
                  {queue.data.map((r) => (
                    <div
                      key={r.decision_id}
                      className="rounded-lg border border-[#23272f] bg-[#121518] p-3 text-xs space-y-2"
                    >
                      <div className="flex items-center justify-between">
                        <button
                          onClick={() => openDecision(r.decision_id)}
                          className="font-mono text-xs text-[#2ebd7b] hover:underline"
                        >
                          {r.decision_id.slice(0, 16)}…
                        </button>
                        <span className="font-semibold text-white">{fmt(r.amount_minor)}</span>
                      </div>
                      <div className="text-[11px] text-[#8b949e]">{r.chosen_action}</div>
                      <div className="flex items-center gap-2 pt-1">
                        <button
                          onClick={async () => {
                            await merchant.review(r.decision_id, true);
                            queue.refresh();
                            ledger.refresh();
                          }}
                          className="flex-1 rounded bg-[#2ebd7b] py-1 text-center text-xs font-semibold text-[#051a10] hover:bg-[#28a76d]"
                        >
                          Approve
                        </button>
                        <button
                          onClick={async () => {
                            await merchant.review(r.decision_id, false);
                            queue.refresh();
                          }}
                          className="flex-1 rounded border border-[#23272f] bg-[#1a1f26] py-1 text-center text-xs text-white hover:bg-[#252c36]"
                        >
                          Reject
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="my-6 text-center">
                  <div className="mx-auto flex h-8 w-8 items-center justify-center rounded-full bg-[#13261c] text-[#2ebd7b]">
                    ✓
                  </div>
                  <div className="mt-2 text-xs font-medium text-white">Nothing waiting for review</div>
                  <p className="mt-0.5 text-[11px] text-[#8b949e]">
                    Autonomous actions execute within the ceiling.
                  </p>
                </div>
              )}
            </div>

            <div className="border-t border-[#181b20] pt-3 text-xs text-[#6e7681]">
              Switch policy mode to &quot;review first&quot; to gate all actions.
            </div>
          </div>

          {/* Quick Actions Card */}
          <div className="flex flex-col justify-between rounded-2xl border border-[#1b1f24] bg-[#0d0f0e] p-5">
            <div>
              <div className="flex items-center gap-1.5 text-xs font-medium text-white">
                <svg className="h-3.5 w-3.5 text-[#2ebd7b]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
                <span>Quick Actions</span>
              </div>
              <div className="mt-3 space-y-2">
                <button
                  disabled={runningS1}
                  onClick={runScenarioS1}
                  className="flex w-full items-center justify-between rounded-lg border border-[#23272f] bg-[#121518] px-3 py-2 text-left text-xs text-[#8b949e] hover:border-[#2ebd7b]/40 hover:text-white disabled:opacity-50"
                >
                  <span>{runningS1 ? "Running S1…" : "Run S1 (Autonomous save)"}</span>
                  <span className="text-[#2ebd7b]">▶</span>
                </button>
                <Link
                  href="/judge"
                  className="flex items-center justify-between rounded-lg border border-[#23272f] bg-[#121518] px-3 py-2 text-xs text-[#8b949e] hover:border-[#2ebd7b]/40 hover:text-white"
                >
                  <span>Judge Mode (scenarios S1–S6)</span>
                  <span className="text-[#2ebd7b]">→</span>
                </Link>
                <Link
                  href="/merchant"
                  className="flex items-center justify-between rounded-lg border border-[#23272f] bg-[#121518] px-3 py-2 text-xs text-[#8b949e] hover:border-[#2ebd7b]/40 hover:text-white"
                >
                  <span>Full Decision Ledger ({ledger.data?.length ?? 0} rows)</span>
                  <span className="text-[#2ebd7b]">→</span>
                </Link>
                <Link
                  href="/buyer"
                  className="flex items-center justify-between rounded-lg border border-[#23272f] bg-[#121518] px-3 py-2 text-xs text-[#8b949e] hover:border-[#2ebd7b]/40 hover:text-white"
                >
                  <span>Maya&apos;s Agent Inbox &amp; Mandate</span>
                  <span className="text-[#2ebd7b]">→</span>
                </Link>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Decision Ledger Quick View */}
      <div className="rounded-2xl border border-[#1b1f24] bg-[#0d0f0e] p-6">
        <div className="flex items-center justify-between pb-4 border-b border-[#1b1f24]">
          <div>
            <h2 className="text-sm font-semibold text-white">Latest Recovery Decisions</h2>
            <p className="mt-0.5 text-xs text-[#8b949e]">
              Click any row to open the per-option arithmetic &amp; constraints inspector
            </p>
          </div>
          <Link
            href="/merchant"
            className="text-xs font-semibold text-[#2ebd7b] hover:underline"
          >
            View full AG Grid table →
          </Link>
        </div>

        <div className="mt-4 overflow-x-auto">
          {ledger.data && ledger.data.length > 0 ? (
            <table className="w-full text-left text-xs">
              <thead className="text-[#6e7681] border-b border-[#1b1f24]">
                <tr>
                  <th className="pb-2 font-normal">When</th>
                  <th className="pb-2 font-normal">Intent ID</th>
                  <th className="pb-2 font-normal">Channel</th>
                  <th className="pb-2 font-normal text-right">Amount</th>
                  <th className="pb-2 font-normal">Failure</th>
                  <th className="pb-2 font-normal">Action</th>
                  <th className="pb-2 font-normal text-right">NEV</th>
                  <th className="pb-2 font-normal">Outcome</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#181b20]">
                {ledger.data.slice(0, 8).map((r) => (
                  <tr
                    key={r.decision_id}
                    onClick={() => openDecision(r.decision_id)}
                    className="cursor-pointer hover:bg-[#121518] transition-colors"
                  >
                    <td className="py-2.5 text-[#8b949e]">
                      {new Date(r.created_at).toLocaleTimeString()}
                    </td>
                    <td className="py-2.5 font-mono text-[11px] text-[#2ebd7b]">
                      {r.intent_id.slice(0, 16)}…
                    </td>
                    <td className="py-2.5 text-white capitalize">{r.channel}</td>
                    <td className="py-2.5 text-right font-medium text-white">
                      {fmt(r.amount_minor, r.currency_code)}
                    </td>
                    <td className="py-2.5 font-mono text-[11px] text-[#8b949e]">
                      {r.failure_class}
                    </td>
                    <td className="py-2.5 text-white font-medium">
                      {r.chosen_action}
                    </td>
                    <td className="py-2.5 text-right font-mono text-[#2ebd7b]">
                      {r.nev_minor !== null ? fmt(r.nev_minor, r.currency_code) : "–"}
                    </td>
                    <td className="py-2.5">
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                          r.outcome === "RECOVERED" || r.outcome === "ORGANIC"
                            ? "bg-[#13261c] text-[#2ebd7b]"
                            : r.outcome === "LOST"
                            ? "bg-[#281618] text-[#d0545e]"
                            : "bg-[#161a22] text-[#8b949e]"
                        }`}
                      >
                        {r.outcome ?? "PENDING"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="py-6 text-center text-xs text-[#8b949e]">
              No decisions yet. Run a scenario from Judge mode to produce real recovery records.
            </p>
          )}
        </div>
      </div>

      {/* Decision Inspector Modal */}
      {selectedDecisionId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div
            className="fixed inset-0 bg-black/80 backdrop-blur-sm"
            onClick={() => setSelectedDecisionId(null)}
          />
          <div className="relative w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-2xl border border-[#23272f] bg-[#0d0f0e] p-6 shadow-2xl">
            <div className="flex items-center justify-between border-b border-[#1b1f24] pb-4">
              <h3 className="text-base font-semibold text-white">Decision Inspector</h3>
              <button
                onClick={() => setSelectedDecisionId(null)}
                className="rounded-lg p-1 text-[#6e7681] hover:bg-[#1a1f26] hover:text-white"
              >
                ✕
              </button>
            </div>

            <div className="mt-4">
              {loadingDecision ? (
                <p className="py-8 text-center text-xs text-[#8b949e]">Loading decision detail…</p>
              ) : decisionError ? (
                <p className="py-8 text-center text-xs text-[#d0545e]">
                  Could not load decision: {decisionError}
                </p>
              ) : selectedDecision ? (
                <DecisionInspector
                  d={selectedDecision}
                  floorMinor={controls.data ? Number(controls.data.ev_floor_minor) : undefined}
                />
              ) : (
                <p className="py-8 text-center text-xs text-[#8b949e]">Decision not found.</p>
              )}
            </div>

            <div className="mt-6 flex justify-end border-t border-[#1b1f24] pt-4">
              <button
                onClick={() => setSelectedDecisionId(null)}
                className="rounded-lg border border-[#23272f] bg-[#121518] px-4 py-2 text-xs font-medium text-white hover:bg-[#1a1f26]"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
