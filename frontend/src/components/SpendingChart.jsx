import { useState } from 'react';
import { ChevronDown, Pencil } from 'lucide-react';
import { spendByCategory } from '../lib/calc';
import { money, shortDate } from '../lib/format';
import { isReadOnly, itemKey } from '../lib/urgency';

const SLOTS = 6; // categories with their own colour; the rest share "Other"
const colour = (i) => (i < SLOTS ? `var(--series-${i + 1})` : 'var(--series-other)');
const pct = (part, whole) => (whole > 0 ? Math.round((part / whole) * 100) : 0);

// Pie (as a ring, so the total fits in the middle): radius and thickness in SVG units.
const R = 52;
const RING = 22;
const C = 2 * Math.PI * R;
const GAP = 1.5; // surface gap between slices, in SVG units along the ring

/** Where the money went: a pie by category, then every category ranked largest first.
 *  Tap a slice or a category to see its expenses. */
export default function SpendingChart({ expenses, emptyText, onEdit, label = 'Spending by category' }) {
  const { rows, total } = spendByCategory(expenses);
  const [open, setOpen] = useState(null); // category name, lower-cased

  if (!rows.length) return <p className="text-sm text-stone-500 dark:text-stone-400">{emptyText}</p>;

  // the top categories get their own colour and slice; the tail folds into one "Other" slice
  const slices = rows.slice(0, SLOTS).map((r, i) => ({ name: r.category, key: r.category.toLowerCase(), amount: r.amount, fill: colour(i) }));
  const rest = rows.slice(SLOTS).reduce((s, r) => s + r.amount, 0);
  if (rest > 0) slices.push({ name: 'Other', key: null, amount: rest, fill: colour(SLOTS) });
  let start = 0;
  const arcs = slices.map((sl) => {
    const len = (sl.amount / total) * C;
    const arc = { ...sl, len, start };
    start += len;
    return arc;
  });
  const gap = arcs.length > 1 ? GAP : 0;

  return (
    <div>
      <div className="flex justify-center">
        <svg viewBox="0 0 140 140" className="h-44 w-44" role="img"
          aria-label={`${label}: ${slices.map((b) => `${b.name} ${money(b.amount)} (${pct(b.amount, total)}%)`).join(', ')}`}>
          <g transform="rotate(-90 70 70)">
            {arcs.map((a) => (
              <circle key={a.name} cx="70" cy="70" r={R} fill="none" stroke={a.fill} strokeWidth={RING}
                strokeDasharray={`${Math.max(a.len - gap, 0.5)} ${C}`} strokeDashoffset={-a.start}
                className={a.key ? 'cursor-pointer' : undefined}
                opacity={open && a.key !== open ? 0.35 : 1}
                onClick={a.key ? () => setOpen(open === a.key ? null : a.key) : undefined}>
                <title>{`${a.name}: ${money(a.amount)} (${pct(a.amount, total)}%)`}</title>
              </circle>
            ))}
          </g>
          <text x="70" y="66" textAnchor="middle" className="fill-stone-500 text-[9px] dark:fill-stone-400">Total</text>
          <text x="70" y="81" textAnchor="middle" className="num fill-stone-900 text-[13px] font-semibold dark:fill-stone-100">
            {money(total)}
          </text>
        </svg>
      </div>

      <ul className="mt-3 divide-y divide-stone-100 dark:divide-neutral-800" aria-label={label}>
        {rows.map((r, i) => {
          const key = r.category.toLowerCase();
          const expanded = open === key;
          return (
            <li key={key} data-category={r.category}>
              <button
                className="flex w-full items-center gap-2.5 py-2 text-left"
                onClick={() => setOpen(expanded ? null : key)}
                aria-expanded={expanded}
              >
                <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: colour(i) }} aria-hidden="true" />
                <span className="min-w-0 flex-1 truncate text-sm">{r.category}</span>
                <span className="num shrink-0 text-xs text-stone-500 dark:text-stone-400">{pct(r.amount, total)}%</span>
                <span className="num w-24 shrink-0 text-right text-sm font-semibold">{money(r.amount)}</span>
                <ChevronDown className={`h-4 w-4 shrink-0 text-stone-400 transition-transform ${expanded ? 'rotate-180' : ''}`} />
              </button>
              {expanded && (
                <ul className="mb-2 ml-5 space-y-1 border-l-2 border-stone-100 pl-2 text-xs text-stone-500 dark:border-neutral-800 dark:text-stone-400">
                  {r.items.map((e) => (
                    <li key={itemKey(e)} className="flex items-center justify-between gap-3">
                      <span className="min-w-0 truncate">{shortDate(e.due_date)} · {e.name}</span>
                      <span className="num flex shrink-0 items-center gap-1">
                        {money(e.amount - (e.reimbursed || 0))}
                        {onEdit && !isReadOnly(e) && (
                          <button className="btn-ghost p-1" onClick={() => onEdit(e)} aria-label={`Edit ${e.name}`} title="Edit">
                            <Pencil className="h-3.5 w-3.5" />
                          </button>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
      <p className="num mt-2 border-t border-stone-200 pt-2 text-right text-sm text-stone-600 dark:border-neutral-800 dark:text-stone-300">
        Total <strong>{money(total)}</strong>
      </p>
    </div>
  );
}
