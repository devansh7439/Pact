/** Typed client for the buyer-agent API (doc 07 §4). */

export const BUYER_URL = process.env.NEXT_PUBLIC_BUYER_URL ?? "http://localhost:8200";

export type Decision = "ACCEPT" | "ESCALATE" | "REJECT";
export type CheckStatus = "pass" | "fail" | "skip";

export interface GuardCheck {
  rule: string;
  status: CheckStatus;
  label: string;
}

export interface GuardDecision {
  gd_id: string;
  offer_id: string | null;
  purchase_id: string;
  result: Decision;
  rule_fired: string;
  option_id: string | null;
  alias: string | null;
  reason: string;
  checks: GuardCheck[];
  checklist: string;
  created_at: string;
}

export interface OfferReceived {
  offer_id: string;
  purchase_id: string;
  body: string; // exact signed bytes as received
  signature_ok: boolean;
  signature_error: string | null;
  scanner_flags: string[];
  received_at: string;
}

export interface Purchase {
  purchase_id: string;
  merchant_id: string;
  intent_id: string | null;
  sku: string | null;
  category: string | null;
  amount_minor: number;
  currency_code: string;
  funding_alias: string;
  autonomous_recoveries: number;
  failed_aliases: string[];
  status: string;
  outcome: string | null;
  created_at: string;
  updated_at: string;
}

export interface PurchaseDetail extends Purchase {
  guard_decisions: GuardDecision[];
  offers: OfferReceived[];
}

export interface InboxMessage {
  msg_id: string;
  kind: "ESCALATION" | "RECEIPT" | "SECURITY" | "INFO";
  text: string;
  approve_url: string | null;
  purchase_id: string | null;
  status: string;
  created_at: string;
}

export interface MandateBody {
  mandate_id: string;
  principal: { display_name: string; paypal_payer_id?: string };
  merchant_scope: string[];
  currency_code: string;
  budget: { period: "DAY" | "WEEK" | "MONTH"; limit_minor: number };
  per_purchase_cap_minor: number;
  allowed_categories: string[];
  funding: { alias: string; kind: "CARD" | "PAYPAL_WALLET"; priority: number }[];
  recovery: {
    allow_alternate_funding: boolean;
    allow_retry_after: boolean;
    max_autonomous_recoveries_per_purchase: number;
    always_escalate_classes: string[];
  };
  expires_at: string;
}

export interface MandateRow {
  mandate_id: string;
  status: "DRAFT" | "ACTIVE" | "REVOKED" | "EXPIRED";
  body: MandateBody;
}

export interface Budget {
  period: string;
  limit_minor: number;
  spent_minor: number;
  remaining_minor: number;
  currency_code: string;
}

export interface Health {
  agent_key_id: string;
  agent_public_key?: string;
  llm: string;
  signing_key: string;
  paused: boolean;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BUYER_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* body wasn't JSON */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body?: unknown) =>
  call<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const buyer = {
  health: () => call<Health>("/health"),
  mandates: () => call<MandateRow[]>("/buyer/mandates"),
  draftMandate: (text: string) => post<{ mandate_id: string; mandate: MandateBody }>("/buyer/mandates/draft", { text }),
  activateMandate: (id: string) => post(`/buyer/mandates/${id}/activate`),
  budget: () => call<Budget>("/buyer/budget"),
  purchases: () => call<Purchase[]>("/buyer/purchases"),
  purchase: (id: string) => call<PurchaseDetail>(`/buyer/purchases/${id}`),
  byIntent: (intentId: string) => call<PurchaseDetail>(`/buyer/by-intent/${intentId}`),
  chat: (message: string) => post<{ reply: string; purchase: unknown }>("/buyer/chat", { message }),
  inbox: () => call<InboxMessage[]>("/buyer/inbox"),
  dismiss: (id: string) => post(`/buyer/inbox/${id}/dismiss`),
  reset: () => post<{ reset: boolean }>("/buyer/reset"),
  pause: () => post<{ paused: boolean }>("/buyer/pause"),
  resume: () => post<{ paused: boolean }>("/buyer/resume"),
};
