/** Integer minor units -> display string. Mirrors shared/money.py `fmt`. */
const ZERO_DECIMAL = new Set(["HUF", "JPY", "TWD"]);

export function fmt(valueMinor: number, currency = "USD"): string {
  const exp = ZERO_DECIMAL.has(currency) ? 0 : 2;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: exp,
    maximumFractionDigits: exp,
  }).format(valueMinor / 10 ** exp);
}
