"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { merchant } from "@/lib/merchant";

interface Scenario {
  id: string;
  title: string;
  tag: string;
  trigger: string;
  summary: string;
  expectedOutcome: string;
  badgeTone: "ok" | "warn" | "neutral";
}

const SCENARIOS: Scenario[] = [
  {
    id: "S1",
    title: "Autonomous Save",
    tag: "Core",
    trigger: "Decline 5120 (Insufficient Funds)",
    summary: "Primary card declines. The merchant offers Maya's saved PayPal wallet; her agent's guard verifies budget headroom and accepts autonomously.",
    expectedOutcome: "Recovered autonomously (no human action needed)",
    badgeTone: "ok",
  },
  {
    id: "S2",
    title: "Refuses to Retry",
    tag: "Core",
    trigger: "Decline 9500 (Suspected Fraud)",
    summary: "Processor returns suspected fraud. Merchant policy bars autonomous retries on high-risk instruments; escalates directly to Maya.",
    expectedOutcome: "Escalated to Maya via one-tap PayPal link",
    badgeTone: "warn",
  },
  {
    id: "S3",
    title: "Retry Limit Exhausted",
    tag: "Core",
    trigger: "Decline 5120 (Repeat Decline)",
    summary: "Card declines, agent tries wallet, wallet also declines. Maya's mandate caps autonomous attempts at 1; guard blocks further retries and escalates.",
    expectedOutcome: "Escalated after attempt ceiling reached",
    badgeTone: "warn",
  },
  {
    id: "S4",
    title: "Low-Value Drop",
    tag: "Core",
    trigger: "Decline 5400 (Expired Card)",
    summary: "A $4.00 item checkout declines. Recovery fees and processing costs exceed expected recovery value; engine drops the payment.",
    expectedOutcome: "Dropped (negative expected value)",
    badgeTone: "neutral",
  },
  {
    id: "S5",
    title: "Prompt Injection Defence",
    tag: "Flash",
    trigger: "Decline with Injected Text",
    summary: "Adversarial text in the payment metadata attempts to override agent instructions. Scanner intercepts and drops untrusted directives.",
    expectedOutcome: "Injection rejected by guardrail scanner",
    badgeTone: "neutral",
  },
  {
    id: "S6",
    title: "Human Customer Recovery",
    tag: "Optional",
    trigger: "Human Checkout Decline",
    summary: "Arjun's subscription renewal payment fails. The engine diagnoses the decline and generates a friendly email with a secure PayPal checkout link.",
    expectedOutcome: "Checkout link sent to customer inbox",
    badgeTone: "ok",
  },
];

export default function JudgePage() {
  const router = useRouter();
  const [running, setRunning] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resetMsg, setResetMsg] = useState<string | null>(null);

  const [lastRun, setLastRun] = useState<{
    scenario: string;
    intentId: string | null;
    status: string;
    detail?: string | null;
  } | null>(null);

  async function handleReset() {
    setResetting(true);
    setError(null);
    setResetMsg(null);
    try {
      await merchant.judgeReset();
      setResetMsg("Clean slate: all demo intents, purchases, and state have been reset.");
      setLastRun(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setResetting(false);
    }
  }

  async function handleRun(scenarioId: string) {
    setRunning(scenarioId);
    setError(null);
    setResetMsg(null);
    try {
      const res = await merchant.runScenario(scenarioId);
      const status = res.result?.status ?? "completed";
      const detail = res.result?.detail;

      setLastRun({
        scenario: scenarioId,
        intentId: res.intent_id,
        status,
        detail,
      });

      // If there's an intent, we can also let user inspect directly
      if (res.intent_id) {
        // give user a moment to see the card update or navigate
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(null);
    }
  }

  return (
    <div className="space-y-6 max-w-5xl mx-auto pb-12">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between border-b border-[#1b1f24] pb-5">
        <div>
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-[#2ebd7b]" />
            <span className="text-[10px] font-mono uppercase tracking-widest text-[#2ebd7b]">
              PayPal AI Hackathon 2026
            </span>
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-white mt-1">
            Judge Mode · Demo Scenarios
          </h1>
          <p className="text-xs text-[#8b949e] mt-0.5">
            Trigger end-to-end decline recovery scenarios (S1–S6) against real merchant policy and buyer guardrails.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={handleReset}
            disabled={resetting}
            className="rounded-lg border border-[#2ebd7b]/40 bg-[#121518] px-3.5 py-2 text-xs font-semibold text-[#2ebd7b] hover:bg-[#13261c] transition-colors disabled:opacity-50"
          >
            {resetting ? "Resetting…" : "Reset State"}
          </button>
          <Link
            href="/merchant"
            className="rounded-lg border border-[#23272f] bg-[#121518] px-3.5 py-2 text-xs font-medium text-white hover:bg-[#1c2128] transition-colors"
          >
            Ledger Table →
          </Link>
        </div>
      </div>

      {resetMsg && (
        <div className="rounded-xl border border-[#2ebd7b]/40 bg-[#13261c] p-3 text-xs text-[#2ebd7b] flex items-center justify-between">
          <span>{resetMsg}</span>
          <button onClick={() => setResetMsg(null)} className="text-white hover:underline text-[10px]">
            Dismiss
          </button>
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-[#d0545e]/40 bg-[#281618] p-3 text-xs text-[#d0545e] flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-white hover:underline text-[10px]">
            Dismiss
          </button>
        </div>
      )}

      {/* Last Run Banner */}
      {lastRun && (
        <div className="rounded-xl border border-[#2ebd7b]/40 bg-[#0d1f16] p-4 text-xs space-y-2">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-white">
              Scenario {lastRun.scenario} Result:{" "}
              <span className="font-mono text-[#2ebd7b] uppercase">{lastRun.status}</span>
            </span>
            {lastRun.intentId && (
              <Link
                href={`/judge/run/${lastRun.intentId}`}
                className="rounded bg-[#2ebd7b] px-3 py-1 font-semibold text-[#051a10] hover:bg-[#28a76d] transition-all"
              >
                Inspect Two-Pane Linked View →
              </Link>
            )}
          </div>
          {lastRun.detail && <p className="text-[#8b949e]">{lastRun.detail}</p>}
        </div>
      )}

      {/* Scenario Cards Grid */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {SCENARIOS.map((s) => {
          const isCurrentRunning = running === s.id;
          const isJustRan = lastRun?.scenario === s.id;

          return (
            <div
              key={s.id}
              className={`flex flex-col justify-between rounded-2xl border p-5 transition-all ${
                isJustRan
                  ? "border-[#2ebd7b] bg-[#0c1a14]"
                  : "border-[#1b1f24] bg-[#0d0f0e] hover:border-[#28303a]"
              }`}
            >
              <div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-[#161a22] px-2 py-0.5 text-xs font-mono font-bold text-white">
                      {s.id}
                    </span>
                    <h3 className="text-sm font-bold text-white">{s.title}</h3>
                  </div>
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] font-semibold font-mono uppercase ${
                      s.badgeTone === "ok"
                        ? "bg-[#13261c] text-[#2ebd7b]"
                        : s.badgeTone === "warn"
                        ? "bg-[#2b2210] text-[#eab308]"
                        : "bg-[#161a22] text-[#8b949e]"
                    }`}
                  >
                    {s.tag}
                  </span>
                </div>

                <div className="mt-2 text-xs font-mono text-[#2ebd7b]">{s.trigger}</div>
                <p className="mt-2 text-xs text-[#8b949e] leading-relaxed">{s.summary}</p>
                <div className="mt-3 text-[11px] text-[#6e7681]">
                  Expected: <span className="text-[#cbd5e1]">{s.expectedOutcome}</span>
                </div>
              </div>

              <div className="mt-5 flex items-center justify-between border-t border-[#1b1f24] pt-3">
                <button
                  disabled={running !== null || resetting}
                  onClick={() => handleRun(s.id)}
                  className="rounded-lg bg-[#2ebd7b] px-4 py-1.5 text-xs font-semibold text-[#051a10] hover:bg-[#28a76d] transition-all disabled:opacity-50"
                >
                  {isCurrentRunning ? "Executing…" : `Run ${s.id}`}
                </button>

                {isJustRan && lastRun.intentId && (
                  <Link
                    href={`/judge/run/${lastRun.intentId}`}
                    className="text-xs font-medium text-[#2ebd7b] hover:underline"
                  >
                    View Timeline →
                  </Link>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
