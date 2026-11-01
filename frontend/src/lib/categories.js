// Suggested so a brand-new account has something to pick from; any other name can be typed.
export const DEFAULT_CATEGORIES = [
  'Rent', 'Utilities', 'Food', 'Subscriptions', 'Credit Cards',
  'Investments', 'Transport', 'Insurance', 'Health', 'Shopping',
];

/** The account's own categories first, then any defaults it does not have yet (case-insensitive). */
export function withDefaults(categories) {
  const seen = new Set(categories.map((c) => c.toLowerCase()));
  return [...categories, ...DEFAULT_CATEGORIES.filter((c) => !seen.has(c.toLowerCase()))];
}
