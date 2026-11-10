import { computeVariance, summarize } from './calc';
import { DEFAULT_CATEGORIES, withDefaults } from './categories';
import { money, signedMoney, localISO, shiftMonth, dayLabel } from './format';

const e = (name, amount, category, paid = false, due_date = '2026-11-01') => ({ name, amount, category, paid, due_date });

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

  it('lists each category\'s expenses by date, matching the category name in any case', () => {
    const w = computeVariance(
      [e('dinner', 600, 'Food', false, '2026-11-20'), e('lunch', 300, 'food', false, '2026-11-05')],
      budgets,
    );
    expect(w.rows.find((r) => r.category === 'Food').items.map((i) => i.name)).toEqual(['lunch', 'dinner']);
    expect(w.rows.find((r) => r.category === 'Rent').items).toEqual([]);
  });

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

describe('withDefaults', () => {
  it('keeps your categories first and skips defaults you already have, ignoring case', () => {
    const out = withDefaults(['Pets', 'rent']);
    expect(out.slice(0, 2)).toEqual(['Pets', 'rent']);
    expect(out).not.toContain('Rent');
    expect(out).toHaveLength(2 + DEFAULT_CATEGORIES.length - 1);
  });
  it('gives an empty account the defaults', () => {
    expect(withDefaults([])).toEqual(DEFAULT_CATEGORIES);
  });
});

describe('paid back by someone else', () => {
  const card = { name: 'Card', amount: 11000, category: 'Cards', paid: false, reimbursed: 4000 };
  it('leaves the bill in full but only counts your share against the budget', () => {
    const s = summarize([card, e('rent', 2000, 'Rent', true)], 10000);
    expect(s).toMatchObject({
      paid: 2000, unpaid: 11000, scheduled: 13000, reimbursed: 4000, own: 9000,
      paidOwn: 2000, unpaidOwn: 7000, remaining: 1000, remainingAfterPaid: 8000, percentCommitted: 90,
    });
  });
  it('keeps a category under target when the overspend was paid back', () => {
    const v = computeVariance([card], [{ category: 'Cards', monthly_target: 8000 }]);
    expect(v.rows[0]).toMatchObject({ actual: 7000, reimbursed: 4000, variance: 1000, status: 'under' });
  });
});
