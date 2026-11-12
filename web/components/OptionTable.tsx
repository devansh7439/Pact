import type { OptionRow } from "@/lib/merchant";
import { fmt } from "@/lib/money";

const VERDICT: Record<OptionRow["verdict"], { label: string; tone: string }> = {
  chosen: { label: "chosen", tone: "text-ok font-medium" },
  offered: { label: "offered", tone: "text-accent" },
  below_floor: { label: "below floor", tone: "text-warn" },
  not_best: { label: "not best", tone: "text-muted" },
  removed: { label: "removed", tone: "text-bad" },
  baseline: { label: "baseline", tone: "text-muted" },
};

const pct = (x?: number) => (x === undefined ? "–" : `${(x * 100).toFixed(1)}%`);
const money = (x: number | undefined, cur: string) => (x === undefined ? "–" : fmt(x, cur));

/** Per-option table (doc 05 §3): every candidate with p(a), p0, lift, cost and NEV, and the rule that removed it. */
export function OptionTable({ options, currency, floorMinor }: { options: OptionRow[]; currency: string; floorMinor?: number }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[36rem] text-sm">
        <caption className="mb-1 text-left text-xs text-muted">
          NEV(a) = (p(a) − p0) · V − C(a)
          {floorMinor !== undefined && <> · floor {fmt(floorMinor, currency)}</>} · probabilities are model estimates
        </caption>
        <thead className="text-left text-xs text-muted">
          <tr className="border-b border-line">
            <th className="py-1 pr-3 font-normal">Action</th>
            <th className="py-1 pr-3 text-right font-normal">p(a)</th>
            <th className="py-1 pr-3 text-right font-normal">p0</th>
            <th className="py-1 pr-3 text-right font-normal">Lift</th>
            <th className="py-1 pr-3 text-right font-normal">Cost</th>
            <th className="py-1 pr-3 text-right font-normal">NEV</th>
            <th className="py-1 font-normal">Verdict</th>
          </tr>
        </thead>
        <tbody className="font-mono text-xs">
          {options.map((o, i) => (
            <tr
              key={`${o.action}-${i}`}
              className={`border-b border-line/60 ${o.verdict === "chosen" ? "bg-ok/5" : ""} ${
                o.verdict === "removed" ? "text-muted" : ""
              }`}
            >
              <td className="py-1 pr-3 font-sans text-sm">{o.action}</td>
              <td className="py-1 pr-3 text-right">{pct(o.p_action)}</td>
              <td className="py-1 pr-3 text-right">{pct(o.p0)}</td>
              <td className="py-1 pr-3 text-right">{pct(o.lift)}</td>
              <td className="py-1 pr-3 text-right">{money(o.cost_minor, currency)}</td>
              <td className={`py-1 pr-3 text-right ${(o.net_ev_minor ?? 0) < 0 ? "text-bad" : ""}`}>
                {money(o.net_ev_minor, currency)}
              </td>
              <td className="py-1 font-sans">
                <span className={VERDICT[o.verdict]?.tone ?? ""}>{VERDICT[o.verdict]?.label ?? o.verdict}</span>
                {o.removed_by && <span className="ml-2 font-mono text-xs text-muted">{o.removed_by}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
