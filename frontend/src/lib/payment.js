export const PAYMENT_MODES = [
  ['cash', 'Cash'],
  ['upi', 'UPI'],
  ['debit_card', 'Debit card'],
  ['net_banking', 'Net banking'],
  ['credit_card', 'Credit card'],
];

const LABEL = Object.fromEntries(PAYMENT_MODES);

/** "HDFC card", "SBI debit card", "UPI", ... for a row, or null when no mode was recorded. */
export function paidWith(item, cards) {
  const card = item.card_id != null && cards.find((c) => c.id === item.card_id);
  if (card) return item.payment_mode === 'debit_card' ? `${card.name} debit card` : `${card.name} card`;
  return LABEL[item.payment_mode] ?? null;
}

/** Which kind of card a payment mode uses, if any. */
export const cardKindFor = (mode) => (mode === 'credit_card' ? 'credit' : mode === 'debit_card' ? 'debit' : null);

/** Amount text input -> number (commas, spaces and ₹ allowed), or NaN. Empty -> null. */
export function parseAmount(text) {
  const t = String(text ?? '').replace(/[,\s₹]/g, '');
  if (t === '') return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : NaN;
}
