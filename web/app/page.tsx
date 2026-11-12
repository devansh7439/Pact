import Link from "next/link";

const CARDS = [
  { href: "/judge", title: "Judge mode", body: "Run the scenarios end to end and see both sides of each recovery." },
  { href: "/merchant", title: "Merchant console", body: "Decisions, the per-option table, holdout lift and controls." },
  { href: "/buyer", title: "Maya's agent", body: "Mandate, budget, purchases with the guard checklist, and the inbox." },
];

export default function Home() {
  return (
    <div className="space-y-8">
      <section className="max-w-2xl space-y-3">
        <h1 className="text-2xl font-semibold tracking-tight">When an agent&apos;s payment is declined, nobody is at the checkout.</h1>
        <p className="text-muted">
          Pact&apos;s merchant engine diagnoses the decline and sends a signed recovery offer. The buyer&apos;s agent
          checks it against the mandate its human approved, then either recovers on its own or asks the human.
          Models predict, policies decide, and no LLM output can move money.
        </p>
      </section>
      <div className="grid gap-4 sm:grid-cols-3">
        {CARDS.map((c) => (
          <Link key={c.href} href={c.href} className="rounded-lg border border-line bg-surface p-4 hover:border-accent">
            <h2 className="font-medium">{c.title}</h2>
            <p className="mt-1 text-sm text-muted">{c.body}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
