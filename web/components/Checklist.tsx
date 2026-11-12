import type { GuardDecision } from "@/lib/buyer";

const MARK = { pass: "✓", fail: "✗", skip: "–" } as const;
const TAIL = { ACCEPT: "Accepted automatically", ESCALATE: "Asked Maya to decide", REJECT: "Rejected" } as const;
const TONE = { ACCEPT: "text-ok", ESCALATE: "text-warn", REJECT: "text-bad" } as const;

/** The guard checklist (doc 06 §2), rendered from structured checks, never from offer prose. */
export function Checklist({ gd, title }: { gd: GuardDecision; title?: string }) {
  return (
    <div className="rounded-md border border-line bg-surface p-3 text-sm">
      {title && <p className="mb-2 font-medium">{title}</p>}
      <ul className="space-y-1">
        {gd.checks.map((c, i) => (
          <li
            key={i}
            className={`flex gap-2 ${c.status === "fail" ? "rounded bg-bad/10 px-1 text-bad" : ""}`}
          >
            <span aria-hidden className={`w-4 shrink-0 font-mono ${c.status === "pass" ? "text-ok" : ""}`}>
              {MARK[c.status]}
            </span>
            <span>
              {c.label}
              <span className="ml-2 font-mono text-xs text-muted">{c.rule}</span>
            </span>
          </li>
        ))}
      </ul>
      <p className={`mt-2 font-medium ${TONE[gd.result]}`}>
        → {TAIL[gd.result]}
        <span className="ml-2 font-mono text-xs text-muted">
          {gd.rule_fired} · {gd.reason}
        </span>
      </p>
    </div>
  );
}
