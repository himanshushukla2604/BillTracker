import { SlidersHorizontal } from 'lucide-react';
import { money, signedMoney } from '../lib/format';

const TONE = {
  under: { text: 'text-emerald-600 dark:text-emerald-400', bar: 'bg-emerald-500', note: 'under target' },
  over: { text: 'text-rose-600 dark:text-rose-400', bar: 'bg-rose-500', note: 'over target' },
  on: { text: 'text-stone-600 dark:text-stone-300', bar: 'bg-emerald-500', note: 'on target' },
  no_target: { text: 'text-stone-400 dark:text-stone-500', bar: 'bg-stone-400 dark:bg-neutral-600', note: 'no target set' },
};

export default function VarianceModule({ variance, monthLabel, onEditTargets, className = '' }) {
  const { rows, totalVariance, totalTarget, totalActual, unbudgeted } = variance;
  const totalStatus = totalVariance > 0 ? 'under' : totalVariance < 0 ? 'over' : 'on';
  const tt = TONE[totalStatus];

  return (
    <section className={`card p-5 ${className}`} aria-labelledby="variance-h">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h2 id="variance-h" className="text-base font-semibold">Spend variance</h2>
          <p className="text-xs text-stone-500 dark:text-stone-400">Target vs actual · {monthLabel}</p>
        </div>
        <button className="btn-outline px-2.5 py-1.5 text-xs" onClick={onEditTargets}>
          <SlidersHorizontal className="h-3.5 w-3.5" /> Targets
        </button>
      </div>

      <div className="mt-4 rounded-xl bg-stone-100 px-4 py-3 dark:bg-neutral-800">
        <p className="text-xs text-stone-500 dark:text-stone-400">Total deviation</p>
        <p className={`num text-3xl font-bold ${tt.text}`} data-testid="total-variance">
          {signedMoney(totalVariance)}
        </p>
        <p className="num mt-0.5 text-xs text-stone-500 dark:text-stone-400">
          {money(totalActual)} spent vs {money(totalTarget)} targeted
          {unbudgeted > 0 && ` · includes ${money(unbudgeted)} with no target`}
        </p>
      </div>

      {rows.length === 0 ? (
        <p className="mt-5 text-center text-sm text-stone-500 dark:text-stone-400">
          No expenses or targets for this month yet.
        </p>
      ) : (
        <ul className="mt-4 space-y-4">
          {rows.map((r) => {
            const t = TONE[r.status];
            const scale = Math.max(r.target ?? 0, r.actual, 1);
            return (
              <li key={r.category} data-status={r.status}>
                <div className="flex items-baseline justify-between gap-3">
                  <span className="truncate text-sm font-medium">{r.category}</span>
                  <span className={`num shrink-0 text-sm font-bold ${t.text}`}>
                    {r.variance == null ? '—' : signedMoney(r.variance)}
                  </span>
                </div>
                <div className="relative mt-1.5 h-2 rounded-full bg-stone-100 dark:bg-neutral-800">
                  <div
                    className={`absolute inset-y-0 left-0 rounded-full ${t.bar}`}
                    style={{ width: `${(r.actual / scale) * 100}%` }}
                  />
                  {r.target != null && (
                    <div
                      className="absolute -bottom-0.5 -top-0.5 w-0.5 rounded bg-stone-800 dark:bg-stone-100"
                      style={{ left: `calc(${(r.target / scale) * 100}% - 1px)` }}
                      title={`Target ${money(r.target)}`}
                    />
                  )}
                </div>
                <p className="num mt-1 text-xs text-stone-500 dark:text-stone-400">
                  {money(r.actual)} {r.target != null ? `of ${money(r.target)}` : 'spent'} · {t.note}
                </p>
              </li>
            );
          })}
        </ul>
      )}
      <p className="mt-4 text-[11px] text-stone-400 dark:text-stone-500">
        + means under target (good) · − means over target. Actual counts every bill dated in the month, paid or not.
      </p>
    </section>
  );
}
