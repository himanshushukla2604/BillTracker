import { computeVariance, summarize } from './calc';
import { money, signedMoney, localISO, shiftMonth, dayLabel } from './format';

const e = (name, amount, category, paid = false) => ({ name, amount, category, paid });

describe('summarize', () => {
  it('remaining = budget - (paid + unpaid)', () => {
    const s = summarize([e('a', 300, 'X', true), e('b', 200, 'X')], 1000);
    expect(s).toMatchObject({ paid: 300, unpaid: 200, scheduled: 500, remaining: 500, remainingAfterPaid: 700, percentCommitted: 50 });
  });
  it('handles zero budget and overspend', () => {
    expect(summarize([e('a', 50, 'X')], 0)).toMatchObject({ remaining: -50, percentCommitted: 0 });
    expect(summarize([e('a', 1500, 'X')], 1000).remaining).toBe(-500);
  });
  it('reports the projected part of what is still to pay', () => {
    const s = summarize([e('a', 300, 'X', true), e('b', 200, 'X'), { ...e('c', 500, 'X'), projected: true }], 1000);
    expect(s).toMatchObject({ unpaid: 700, projected: 500, remaining: 0 });
  });
  it('avoids floating point drift', () => {
    expect(summarize([e('a', 0.1, 'X'), e('b', 0.2, 'X')], 1).scheduled).toBe(0.3);
  });
});

describe('computeVariance', () => {
  const budgets = [
    { category: 'Food', monthly_target: 1000 },
    { category: 'Rent', monthly_target: 5000 },
    { category: 'Travel', monthly_target: 400 },
  ];
  const v = computeVariance(
    [e('g', 1300, 'food'), e('r', 5000, 'Rent'), e('m', 250, 'Misc')],
    budgets,
  );
  const row = (c) => v.rows.find((r) => r.category === c);

  it('uses target - actual with the right sign and status', () => {
    expect(row('Food')).toMatchObject({ variance: -300, status: 'over', actual: 1300 });
    expect(row('Rent')).toMatchObject({ variance: 0, status: 'on' });
    expect(row('Travel')).toMatchObject({ variance: 400, status: 'under' });
    expect(row('Misc')).toMatchObject({ variance: null, status: 'no_target' });
  });
  it('merges categories case-insensitively', () => {
    expect(v.rows.filter((r) => r.category.toLowerCase() === 'food')).toHaveLength(1);
  });
  it('totals and ordering', () => {
    expect(v).toMatchObject({ totalTarget: 6400, totalActual: 6550, totalVariance: -150, unbudgeted: 250 });
    expect(v.rows.map((r) => r.category)).toEqual(['Food', 'Rent', 'Travel', 'Misc']); // worst first, no-target last
  });
});

describe('format', () => {
  it('formats rupees in Indian grouping, showing paise only when present', () => {
    expect(money(123456)).toBe('₹1,23,456');
    expect(money(1450.5)).toBe('₹1,450.50');
  });
  it('signs deviations', () => {
    expect(signedMoney(1200)).toBe('+₹1,200');
    expect(signedMoney(-800)).toBe('−₹800');
    expect(signedMoney(0)).toBe('₹0');
  });
  it('uses the local calendar date', () => {
    expect(localISO(new Date(2026, 10, 1, 0, 5))).toBe('2026-11-01');
  });
  it('shifts months across year boundaries', () => {
    expect(shiftMonth('2026-12', 1)).toBe('2027-01');
    expect(shiftMonth('2026-01', -1)).toBe('2025-12');
  });
  it('labels relative days', () => {
    expect(dayLabel('2026-11-01', '2026-11-01')).toBe('Today');
    expect(dayLabel('2026-11-02', '2026-11-01')).toBe('Tomorrow');
  });
});
