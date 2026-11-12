"use client";

import { useState } from "react";
import { merchant } from "@/lib/merchant";

interface AskPactProps {
  intentId?: string | null;
}

export function AskPact({ intentId }: AskPactProps) {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{
    question: string;
    answer: string;
    tool_used: string | null;
    data: Record<string, unknown>;
    mode: string;
  } | null>(null);
  const [showRaw, setShowRaw] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const presets = [
    { label: "Recovery Metrics", q: "What is our overall recovery performance and causal lift?" },
    { label: "Causal Holdout", q: "Why does Pact keep a 10% holdout group?" },
    { label: "Recent Failures", q: "Show recent failed intents and their status." },
    ...(intentId
      ? [{ label: `Diagnose ${intentId.slice(0, 12)}…`, q: `Why did ${intentId} decline and what was selected?` }]
      : []),
  ];

  async function handleAsk(queryText: string) {
    if (!queryText.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await merchant.assistantAsk(queryText, intentId ?? undefined);
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="rounded-lg border border-line bg-surface p-4 text-sm shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line pb-3">
        <div className="flex items-center gap-2">
          <div className="h-2.5 w-2.5 rounded-full bg-emerald-400 animate-pulse" />
          <h2 className="text-sm font-semibold uppercase tracking-wider text-primary">
            Ask Pact · Assistant
          </h2>
          <span className="rounded bg-line px-1.5 py-0.5 text-[10px] font-mono text-muted uppercase">
            Read-only
          </span>
        </div>
        <span className="text-xs text-muted">
          PayPal Agent Toolkit &amp; Ledger Audit
        </span>
      </div>

      {/* Preset pills */}
      <div className="mt-3 flex flex-wrap gap-1.5">
        {presets.map((p) => (
          <button
            key={p.label}
            onClick={() => {
              setQuestion(p.q);
              handleAsk(p.q);
            }}
            disabled={loading}
            className="rounded border border-line bg-bg px-2.5 py-1 text-xs text-muted transition hover:border-primary hover:text-primary disabled:opacity-50"
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Input row */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          handleAsk(question);
        }}
        className="mt-3 flex gap-2"
      >
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={intentId ? `Ask about ${intentId} or system metrics...` : "Ask about declines, metrics, or holdouts..."}
          disabled={loading}
          className="flex-1 rounded border border-line bg-bg px-3 py-1.5 text-sm outline-none focus:border-primary disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={loading || !question.trim()}
          className="rounded bg-primary px-4 py-1.5 font-medium text-black transition hover:opacity-90 disabled:opacity-50"
        >
          {loading ? "Auditing…" : "Ask"}
        </button>
      </form>

      {error && (
        <p className="mt-3 rounded border border-bad/40 bg-bad/10 p-2 text-xs text-bad">
          {error}
        </p>
      )}

      {/* Answer display */}
      {result && (
        <div className="mt-4 rounded border border-line/60 bg-bg/50 p-3">
          <div className="flex items-center justify-between gap-2 text-xs text-muted">
            <div className="flex items-center gap-2">
              <span className="font-mono text-emerald-400">
                tool: {result.tool_used ?? "none"}
              </span>
              <span>·</span>
              <span className="font-mono">mode: {result.mode}</span>
            </div>
            {result.data && Object.keys(result.data).length > 0 && (
              <button
                type="button"
                onClick={() => setShowRaw(!showRaw)}
                className="underline hover:text-primary"
              >
                {showRaw ? "Hide raw data" : "View audit JSON"}
              </button>
            )}
          </div>

          <div className="mt-2.5 whitespace-pre-line text-sm leading-relaxed">
            {result.answer}
          </div>

          {showRaw && result.data && (
            <pre className="mt-3 max-h-48 overflow-auto rounded bg-black/50 p-2.5 text-[11px] font-mono text-muted">
              {JSON.stringify(result.data, null, 2)}
            </pre>
          )}
        </div>
      )}
    </section>
  );
}
