/** Typed client for merchant-api (doc 07 §3), matching merchant/app.py and merchant/console.py. */

export const MERCHANT_URL = process.env.NEXT_PUBLIC_MERCHANT_URL ?? "http://localhost:8100";

export type Provenance = "sandbox" | "fixture" | "simulated";

export interface OptionRow {
  action: string;
  verdict: "chosen" | "offered" | "below_floor" | "not_best" | "removed" | "baseline";
  removed_by: string | null;
  p_action?: number;
  p0?: number;
  lift?: number;
  gross_expected_minor?: number;
  fee_minor?: number;
  cost_minor?: number;
  net_ev_minor?: number;
}

export interface StageTrace {
  rule_id: string;
  rationale: string;
  constraints: string[];
  failure_class: string;
  diagnosed_by: string;
  base_propensity: number;
  propensity_source: string;
  offer_actions: string[];
  eligible_funding_aliases: string[];
  execution_blocked_by: string | null;
  /** "judge_scripted" for demo runs (never held out, excluded from lift); null for real traffic. */
  holdout_exempt?: string | null;
}

export interface AuditRow {
  seq: number;
  intent_id: string | null;
  stage: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface Intent {
  intent_id: string;
  customer_id: string;
  channel: "agent" | "human";
  agent_id: string | null;
  mandate_id: string | null;
  amount_minor: number;
  currency_code: string;
  items: unknown;
  state: string;
  outcome: string | null;
  provenance: Provenance;
  created_at: string;
}

export interface MerchantOffer {
  offer_id: string;
  intent_id: string;
  decision_id: string;
  body: Record<string, unknown>; // parsed from body_json
  expires_at: string;
  status: string;
  accepted_option_id: string | null;
}

export interface Outcome {
  intent_id: string;
  outcome: string;
  source: string;
  recovered_minor: number;
  paypal_capture_id: string | null;
  created_at: string;
}

export interface Decision {
  decision_id: string;
  intent_id: string;
  stage_trace: StageTrace;
  chosen_action: string;
  nev_minor: number | null;
  options: OptionRow[];
  held_out: number;
  mode: string;
  review_status: string | null;
  created_at: string;
  labels: { probabilities: string };
  intent?: Intent;
  offers: MerchantOffer[];
  actions: Record<string, unknown>[];
  audit?: AuditRow[];
  outcome: Outcome | null;
}

export interface LedgerRow {
  decision_id: string;
  intent_id: string;
  chosen_action: string;
  nev_minor: number | null;
  held_out: number;
  mode: string;
  review_status: string | null;
  created_at: string;
  channel: "agent" | "human";
  amount_minor: number;
  currency_code: string;
  provenance: Provenance;
  failure_class: string | null;
  diagnosed_by: string | null;
  outcome: string | null;
  judge_scripted?: number;
}

export interface Interval {
  rate: number;
  low: number;
  high: number;
  n: number;
}

export interface ProvenanceMetrics {
  intents_with_failures: number;
  caused_minor: number;
  organic_minor: number;
  gross_minor: number;
  lost_minor: number;
  holdout: { acted: Interval; held_out: Interval; lift: number | null; enough_data: boolean; message: string | null };
}

export interface Metrics {
  by_provenance: Partial<Record<Provenance, ProvenanceMetrics>>;
  note: string;
}

export interface Controls {
  mode: "review_first" | "autonomous";
  kill_switch: "on" | "off";
  ev_floor_minor: string;
  autonomy_ceiling_minor: string;
  max_recovery_attempts: string;
  holdout_rate: string;
  executes: boolean;
}

export interface ReviewItem {
  decision_id: string;
  intent_id: string;
  chosen_action: string;
  nev_minor: number | null;
  amount_minor: number;
  channel: string;
  created_at: string;
}

export interface SecurityEvent {
  id: number;
  kind: string;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface ModelMetrics {
  available: boolean;
  provenance: string;
  roc_auc?: number;
  oracle_auc?: number;
  brier?: number;
  brier_baseline?: number;
  calibration_bins?: { range: string; n: number; predicted: number; observed: number }[];
}

export interface MerchantHealth {
  service: string;
  paypal: string;
  llm: string;
  mode: string;
  kill_switch: string;
  merchant_key_id: string;
}

export interface Attempt {
  attempt_id: string;
  paypal_order_id: string | null;
  paypal_capture_id: string | null;
  funding_alias: string | null;
  status: string;
  processor_code: string | null;
  issue: string | null;
  created_at: string;
}

export interface LinkedMerchant {
  intent: Intent;
  decisions: Decision[];
  attempts: Attempt[];
  outcome: Outcome | null;
  timeline: TimelineEntry[];
}

export interface TimelineEntry {
  at: string;
  side: "merchant" | "buyer";
  stage: string;
  detail: Record<string, unknown>;
}

export interface Linked {
  merchant: LinkedMerchant;
  buyer: import("./buyer").PurchaseDetail | null;
  timeline?: TimelineEntry[];
}

export interface Onboarding {
  merchant: { id: string; name: string };
  agent_id: string;
  status: string;
  mandate: import("./buyer").MandateBody;
  saved_funding: { alias: string; kind: string; status: string }[];
  missing_funding: string[];
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${MERCHANT_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const msg = body?.error?.message ?? body?.error ?? body?.detail ?? res.statusText;
    throw new Error(`${res.status}: ${typeof msg === "string" ? msg : JSON.stringify(msg)}`);
  }
  return body as T;
}

const post = <T>(path: string, body?: unknown) =>
  call<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const merchant = {
  health: () => call<MerchantHealth>("/health"),
  ledger: () => call<LedgerRow[]>("/console/ledger"),
  decision: (id: string) => call<Decision>(`/console/decisions/${id}`),
  metrics: () => call<Metrics>("/console/metrics"),
  controls: () => call<Controls>("/console/controls"),
  setControls: (c: Partial<Record<keyof Controls, string>>) => post<Controls>("/console/controls", c),
  reviewQueue: () => call<ReviewItem[]>("/console/review-queue"),
  review: (id: string, approve: boolean) => post(`/console/review-queue/${id}/${approve ? "approve" : "reject"}`),
  model: () => call<ModelMetrics>("/console/model"),
  security: () => call<SecurityEvent[]>("/console/security-events"),
  feed: (since = 0) => call<{ events: AuditRow[]; next: number }>(`/console/feed?since=${since}`),
  linked: (intentId: string) => call<Linked>(`/judge/linked/${intentId}`),
  judgeReset: () => post("/judge/reset"),
  runScenario: (s: string) =>
    post<{ scenario: string; intent_id: string; channel: string; summary: string }>(`/judge/scenarios/${s}/run`),
  onboarding: (token: string) => call<Onboarding>(`/onboard/${token}`),
  onboardVault: (token: string, alias: string) =>
    post<{ approve_url: string; setup_token: string }>(`/onboard/${token}/vault/paypal`, { alias }),
  onboardConfirm: (token: string, payer_id?: string) =>
    post<{ status: string; mandate_id: string; approval_ref: string }>(`/onboard/${token}/confirm`, { payer_id }),
};
