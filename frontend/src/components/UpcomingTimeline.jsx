import { Check, Pencil, Plus, Repeat } from 'lucide-react';
import { dayLabel, money, shortDate } from '../lib/format';
import { PROJECTED_HINT, URGENCY, dueText, itemKey } from '../lib/urgency';

const RANGES = [7, 30, 90];

function groupItems(items, todayISO) {
  const groups = [];
  const overdue = items.filter((i) => i.days_left < 0);
  if (overdue.length) groups.push({ key: 'overdue', label: 'Overdue', items: overdue });
  const byDate = new Map();
  for (const i of items) {
    if (i.days_left < 0) continue;
    if (!byDate.has(i.due_date)) byDate.set(i.due_date, []);
    byDate.get(i.due_date).push(i);
  }
  for (const [date, its] of byDate) {
    const label = dayLabel(date, todayISO);
    groups.push({ key: date, label, sub: /^(Today|Tomorrow)$/.test(label) ? shortDate(date) : null, items: its });
  }
  return groups;
}

export default function UpcomingTimeline({ items, days, onDaysChange, todayISO, onPay, onEdit, onAdd, className = '' }) {
  const visible = items.filter((i) => i.days_left <= days);
  const groups = groupItems(visible, todayISO);

  return (
    <section className={`card p-5 ${className}`} aria-labelledby="timeline-h">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="timeline-h" className="text-base font-semibold">Upcoming bills</h2>
        <div className="flex items-center gap-2">
          <div role="group" aria-label="Time range" className="inline-flex rounded-lg border border-stone-300 p-0.5 dark:border-neutral-700">
            {RANGES.map((r) => (
              <button
                key={r}
                aria-pressed={days === r}
                onClick={() => onDaysChange(r)}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                  days === r
                    ? 'bg-stone-900 text-white dark:bg-stone-100 dark:text-stone-900'
                    : 'text-stone-600 hover:bg-stone-100 dark:text-stone-300 dark:hover:bg-neutral-800'
                }`}
              >
                {r}d
              </button>
            ))}
          </div>
          <button className="btn-primary" onClick={onAdd}>
            <Plus className="h-4 w-4" /> Add
          </button>
        </div>
      </div>

      <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-stone-500 dark:text-stone-400" aria-label="Colour legend">
        {['overdue', 'urgent', 'soon', 'later'].map((k) => (
          <li key={k} className="flex items-center gap-1.5">
            <span className={`h-2.5 w-2.5 rounded-full ${URGENCY[k].dot}`} /> {URGENCY[k].label}
          </li>
        ))}
      </ul>

      {groups.length === 0 ? (
        <p className="mt-6 rounded-xl border border-dashed border-stone-300 py-10 text-center text-sm text-stone-500 dark:border-neutral-700 dark:text-stone-400">
          Nothing due in the next {days} days. Add a bill to start tracking.
        </p>
      ) : (
        <div className="mt-4 space-y-5">
          {groups.map((g) => (
            <div key={g.key}>
              <div className="mb-2 flex items-baseline justify-between px-1">
                <h3
                  className={`text-xs font-semibold uppercase tracking-wide ${
                    g.key === 'overdue' ? 'text-rose-600 dark:text-rose-400' : 'text-stone-500 dark:text-stone-400'
                  }`}
                >
                  {g.label}
                  {g.sub && <span className="ml-1.5 font-normal normal-case tracking-normal opacity-75">{g.sub}</span>}
                </h3>
                <span className="num text-xs text-stone-500 dark:text-stone-400">
                  {money(g.items.reduce((s, i) => s + i.amount, 0))}
                </span>
              </div>
              <ul className="space-y-2">
                {g.items.map((i) => {
                  const u = URGENCY[i.urgency];
                  return (
                    <li
                      key={itemKey(i)}
                      data-urgency={i.urgency}
                      data-projected={i.projected || undefined}
                      className={`flex items-center gap-3 rounded-xl border border-l-4 border-stone-200 px-3 py-2.5 dark:border-neutral-800 ${u.border} ${
                        i.projected ? 'border-dashed opacity-75' : u.row
                      }`}
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <span className="truncate font-medium">{i.name}</span>
                          {i.recurring !== 'none' && (
                            <Repeat className="h-3.5 w-3.5 shrink-0 text-stone-400" aria-label={`Repeats ${i.recurring}`} />
                          )}
                        </div>
                        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-stone-500 dark:text-stone-400">
                          <span>{i.category}</span>
                          <span className={`rounded-full px-2 py-0.5 font-medium ${u.chip}`}>{dueText(i)}</span>
                          {i.projected && <span title={PROJECTED_HINT}>Projected</span>}
                        </div>
                      </div>
                      <span className="num shrink-0 font-semibold">{money(i.amount)}</span>
                      {!i.projected && (
                        <>
                          <button
                            className="btn-outline shrink-0 px-2.5 py-1.5"
                            onClick={() => onPay(i)}
                            aria-label={`Mark ${i.name} as paid`}
                          >
                            <Check className="h-4 w-4" /> <span className="hidden sm:inline">Paid</span>
                          </button>
                          <button className="btn-ghost shrink-0 p-1.5" onClick={() => onEdit(i)} aria-label={`Edit ${i.name}`}>
                            <Pencil className="h-4 w-4" />
                          </button>
                        </>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
