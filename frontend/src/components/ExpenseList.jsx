import { useEffect, useState } from 'react';
import { Check, Pencil, Repeat, Trash2, Undo2 } from 'lucide-react';
import { money, shortDate } from '../lib/format';
import { PROJECTED_HINT, URGENCY, dueText, itemKey } from '../lib/urgency';

const TABS = [
  ['all', 'All'],
  ['unpaid', 'To pay'],
  ['paid', 'Paid'],
];

export default function ExpenseList({ expenses, monthLabel, onPay, onUnpay, onEdit, onDelete, className = '' }) {
  const [tab, setTab] = useState('all');
  const [confirmId, setConfirmId] = useState(null);

  useEffect(() => {
    if (confirmId == null) return;
    const t = setTimeout(() => setConfirmId(null), 4000);
    return () => clearTimeout(t);
  }, [confirmId]);

  const rows = expenses.filter((e) => tab === 'all' || (tab === 'paid') === e.paid);
  const total = rows.reduce((s, e) => s + e.amount, 0);

  return (
    <section className={`card p-5 ${className}`} aria-labelledby="ledger-h">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="ledger-h" className="text-base font-semibold">All expenses</h2>
          <p className="text-xs text-stone-500 dark:text-stone-400">{monthLabel}</p>
        </div>
        <div role="group" aria-label="Filter" className="inline-flex rounded-lg border border-stone-300 p-0.5 dark:border-neutral-700">
          {TABS.map(([k, label]) => (
            <button
              key={k}
              aria-pressed={tab === k}
              onClick={() => setTab(k)}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                tab === k
                  ? 'bg-stone-900 text-white dark:bg-stone-100 dark:text-stone-900'
                  : 'text-stone-600 hover:bg-stone-100 dark:text-stone-300 dark:hover:bg-neutral-800'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {rows.length === 0 ? (
        <p className="mt-6 rounded-xl border border-dashed border-stone-300 py-8 text-center text-sm text-stone-500 dark:border-neutral-700 dark:text-stone-400">
          No expenses to show for this month.
        </p>
      ) : (
        <>
          <ul className="mt-3 divide-y divide-stone-100 dark:divide-neutral-800">
            {rows.map((e) => {
              const u = URGENCY[e.urgency];
              return (
                <li key={itemKey(e)} data-projected={e.projected || undefined} className={`flex items-center gap-3 py-2.5 ${e.projected ? 'opacity-75' : ''}`}>
                  <div className="w-12 shrink-0 text-center">
                    <span className="num block text-sm font-semibold">{shortDate(e.due_date).split(' ')[0]}</span>
                    <span className="block text-[10px] uppercase text-stone-500 dark:text-stone-400">
                      {shortDate(e.due_date).split(' ')[1]}
                    </span>
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className={`truncate font-medium ${e.paid ? 'text-stone-500 line-through dark:text-stone-500' : ''}`}>
                        {e.name}
                      </span>
                      {e.recurring !== 'none' && (
                        <Repeat className="h-3.5 w-3.5 shrink-0 text-stone-400" aria-label={`Repeats ${e.recurring}`} />
                      )}
                    </div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-stone-500 dark:text-stone-400">
                      <span>{e.category}</span>
                      <span className={`rounded-full px-2 py-0.5 font-medium ${u.chip}`}>
                        {e.paid && e.paid_on ? `Paid ${shortDate(e.paid_on)}` : dueText(e)}
                      </span>
                      {e.projected && <span title={PROJECTED_HINT}>Projected</span>}
                    </div>
                  </div>
                  <span className="num shrink-0 font-semibold">{money(e.amount)}</span>
                  {!e.projected && <div className="flex shrink-0 items-center">
                    {e.paid ? (
                      <button className="btn-ghost p-1.5" onClick={() => onUnpay(e)} aria-label={`Undo payment for ${e.name}`} title="Mark as unpaid">
                        <Undo2 className="h-4 w-4" />
                      </button>
                    ) : (
                      <button className="btn-ghost p-1.5 text-emerald-700 dark:text-emerald-400" onClick={() => onPay(e)} aria-label={`Mark ${e.name} as paid`} title="Mark as paid">
                        <Check className="h-4 w-4" />
                      </button>
                    )}
                    <button className="btn-ghost p-1.5" onClick={() => onEdit(e)} aria-label={`Edit ${e.name}`} title="Edit">
                      <Pencil className="h-4 w-4" />
                    </button>
                    {confirmId === e.id ? (
                      <button
                        className="btn bg-rose-600 px-2 py-1 text-xs text-white hover:bg-rose-700"
                        onClick={() => { setConfirmId(null); onDelete(e); }}
                      >
                        Confirm delete
                      </button>
                    ) : (
                      <button
                        className="btn-ghost p-1.5 text-stone-500 hover:text-rose-600"
                        onClick={() => setConfirmId(e.id)}
                        aria-label={`Delete ${e.name}`}
                        title="Delete"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    )}
                  </div>}
                </li>
              );
            })}
          </ul>
          <p className="num mt-3 border-t border-stone-200 pt-3 text-right text-sm text-stone-600 dark:border-neutral-800 dark:text-stone-300">
            {rows.length} item{rows.length === 1 ? '' : 's'} · <strong>{money(total)}</strong>
          </p>
        </>
      )}
    </section>
  );
}
