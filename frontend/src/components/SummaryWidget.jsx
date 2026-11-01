import { useEffect, useRef, useState } from 'react';
import { Wallet } from 'lucide-react';
import { money } from '../lib/format';

function parseAmount(text) {
  const t = text.replace(/[,\s]/g, '');
  if (t === '') return 0;
  const n = Number(t);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

export default function SummaryWidget({ summary, monthLabel, perDay, daysLeft, onBudgetChange, className = '' }) {
  const { totalBudget, paid, unpaid, projected, remaining, percentCommitted } = summary;
  const [text, setText] = useState(totalBudget ? String(totalBudget) : '');
  const inputRef = useRef(null);

  // Keep the field in sync with the server value unless the user is typing in it.
  useEffect(() => {
    if (document.activeElement !== inputRef.current) setText(totalBudget ? String(totalBudget) : '');
  }, [totalBudget]);

  const over = remaining < 0;
  const tight = !over && totalBudget > 0 && remaining < totalBudget * 0.1;
  const tone = over
    ? 'text-rose-600 dark:text-rose-400'
    : tight
      ? 'text-amber-600 dark:text-amber-400'
      : 'text-emerald-600 dark:text-emerald-400';

  const paidPct = totalBudget > 0 ? Math.min((paid / totalBudget) * 100, 100) : 0;
  const unpaidPct = totalBudget > 0 ? Math.min((unpaid / totalBudget) * 100, 100 - paidPct) : 0;

  return (
    <section className={`card p-5 ${className}`} aria-labelledby="summary-h">
      <div className="flex items-center justify-between">
        <h2 id="summary-h" className="flex items-center gap-2 text-sm font-semibold text-stone-600 dark:text-stone-300">
          <Wallet className="h-4 w-4" /> Remaining budget
        </h2>
        <span className="text-xs text-stone-500 dark:text-stone-400">{monthLabel}</span>
      </div>

      <p className={`num mt-2 text-4xl font-bold tracking-tight ${tone}`} data-testid="remaining">
        {over ? '−' : ''}{money(Math.abs(remaining))}
      </p>
      <p className="mt-1 text-xs text-stone-500 dark:text-stone-400">
        {totalBudget > 0
          ? over
            ? `${money(-remaining)} over your ${money(totalBudget)} budget`
            : `left of ${money(totalBudget)} after all scheduled bills`
          : 'Set a monthly budget below to see what is left'}
      </p>

      <div
        className="mt-4 flex h-2.5 overflow-hidden rounded-full bg-stone-100 dark:bg-neutral-800"
        role="img"
        aria-label={`${percentCommitted}% of budget committed`}
      >
        {over ? (
          <div className="h-full w-full bg-rose-500" />
        ) : (
          <>
            <div className="h-full bg-emerald-600" style={{ width: `${paidPct}%` }} />
            <div className="h-full bg-emerald-300 dark:bg-emerald-800" style={{ width: `${unpaidPct}%` }} />
          </>
        )}
      </div>

      <dl className="num mt-4 space-y-2 text-sm">
        <div className="flex items-center justify-between">
          <dt className="flex items-center gap-2 text-stone-600 dark:text-stone-300">
            <span className="h-2.5 w-2.5 rounded-full bg-emerald-600" /> Paid so far
          </dt>
          <dd className="font-medium">{money(paid)}</dd>
        </div>
        <div className="flex items-center justify-between">
          <dt className="flex items-center gap-2 text-stone-600 dark:text-stone-300">
            <span className="h-2.5 w-2.5 rounded-full bg-emerald-300 dark:bg-emerald-800" /> Still to pay
          </dt>
          <dd className="font-medium">{money(unpaid)}</dd>
        </div>
        {projected > 0 && (
          <p className="-mt-1 pl-[1.125rem] text-xs text-stone-500 dark:text-stone-400">
            incl. {money(projected)} of projected recurring bills
          </p>
        )}
        <div className="flex items-center justify-between gap-3 border-t border-stone-200 pt-3 dark:border-neutral-800">
          <dt>
            <label htmlFor="monthly-budget" className="text-stone-600 dark:text-stone-300">Monthly budget</label>
          </dt>
          <dd className="relative w-36">
            <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-stone-400">₹</span>
            <input
              id="monthly-budget"
              ref={inputRef}
              className="input pl-7 text-right font-medium"
              inputMode="decimal"
              value={text}
              placeholder="0"
              onChange={(e) => {
                setText(e.target.value);
                const n = parseAmount(e.target.value);
                if (n != null) onBudgetChange(n);
              }}
              onBlur={() => setText(totalBudget ? String(totalBudget) : '')}
            />
          </dd>
        </div>
      </dl>

      {perDay != null && remaining > 0 && (
        <p className="mt-4 rounded-lg bg-stone-100 px-3 py-2 text-xs text-stone-600 dark:bg-neutral-800 dark:text-stone-300">
          About <strong className="num">{money(perDay)}</strong> a day is uncommitted for the {daysLeft} day
          {daysLeft === 1 ? '' : 's'} left this month.
        </p>
      )}
    </section>
  );
}
