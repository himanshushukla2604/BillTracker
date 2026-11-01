// Client-side maths so the summary and variance react instantly while the user edits
// (the same rules the API exposes at /api/summary and /api/variance).

export const ALERT_DAYS = 3;
const round2 = (n) => Math.round(n * 100) / 100;

/** Remaining budget = total budget - everything dated in the month (paid, still to pay, projected). */
export function summarize(expenses, totalBudget) {
  let paid = 0;
  let unpaid = 0;
  let projected = 0;
  for (const e of expenses) {
    if (e.paid) paid += e.amount;
    else unpaid += e.amount;
    if (e.projected) projected += e.amount;
  }
  const scheduled = paid + unpaid;
  return {
    totalBudget,
    paid: round2(paid),
    unpaid: round2(unpaid),
    projected: round2(projected), // part of unpaid: recurring bills not created yet
    scheduled: round2(scheduled),
    remaining: round2(totalBudget - scheduled),
    remainingAfterPaid: round2(totalBudget - paid),
    percentCommitted: totalBudget > 0 ? round2((scheduled / totalBudget) * 100) : 0,
  };
}

/** variance = target - actual. Positive = under target (good), negative = over. */
export function computeVariance(expenses, budgets) {
  const map = new Map();
  for (const b of budgets) {
    map.set(b.category.toLowerCase(), { category: b.category, target: b.monthly_target, actual: 0, paid: 0 });
  }
  for (const e of expenses) {
    const key = e.category.toLowerCase();
    if (!map.has(key)) map.set(key, { category: e.category, target: null, actual: 0, paid: 0 });
    const row = map.get(key);
    row.actual += e.amount;
    if (e.paid) row.paid += e.amount;
  }
  const rows = [...map.values()].map((r) => {
    const actual = round2(r.actual);
    const variance = r.target == null ? null : round2(r.target - actual);
    const status = variance == null ? 'no_target' : variance === 0 ? 'on' : variance > 0 ? 'under' : 'over';
    return { ...r, actual, paid: round2(r.paid), variance, status };
  });
  // Worst overspend first, then healthy categories, then un-targeted spending.
  rows.sort((a, b) => {
    if ((a.variance == null) !== (b.variance == null)) return a.variance == null ? 1 : -1;
    if (a.variance != null) return a.variance - b.variance || a.category.localeCompare(b.category);
    return b.actual - a.actual || a.category.localeCompare(b.category);
  });
  const totalTarget = round2(rows.reduce((s, r) => s + (r.target ?? 0), 0));
  const totalActual = round2(rows.reduce((s, r) => s + r.actual, 0));
  return {
    rows,
    totalTarget,
    totalActual,
    totalVariance: round2(totalTarget - totalActual),
    unbudgeted: round2(rows.filter((r) => r.target == null).reduce((s, r) => s + r.actual, 0)),
  };
}
