// Colour coding for due dates. Colour is never the only signal: every state also has a text label.
//   overdue : past due                      (solid red)
//   urgent  : due today or tomorrow         (red)
//   soon    : due in 2-3 days               (amber)
//   later   : due in 4+ days                (neutral)
//   paid                                     (green, muted)
export const URGENCY = {
  overdue: {
    label: 'Overdue',
    border: 'border-l-rose-600',
    row: 'bg-rose-50 dark:bg-rose-950/40',
    chip: 'bg-rose-600 text-white',
    dot: 'bg-rose-600',
  },
  urgent: {
    label: 'Due in 0–1 days',
    border: 'border-l-rose-400',
    row: 'bg-rose-50/70 dark:bg-rose-950/25',
    chip: 'bg-rose-100 text-rose-800 dark:bg-rose-900/60 dark:text-rose-200',
    dot: 'bg-rose-400',
  },
  soon: {
    label: 'Due in 2–3 days',
    border: 'border-l-amber-400',
    row: 'bg-amber-50/80 dark:bg-amber-950/25',
    chip: 'bg-amber-100 text-amber-900 dark:bg-amber-900/50 dark:text-amber-100',
    dot: 'bg-amber-400',
  },
  later: {
    label: 'Later',
    border: 'border-l-stone-300 dark:border-l-neutral-700',
    row: '',
    chip: 'bg-stone-100 text-stone-700 dark:bg-neutral-800 dark:text-stone-300',
    dot: 'bg-stone-300 dark:bg-neutral-600',
  },
  paid: {
    label: 'Paid',
    border: 'border-l-emerald-500',
    row: '',
    chip: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200',
    dot: 'bg-emerald-500',
  },
};

/** React key: projected occurrences have no id until the bill before them is paid. */
export const itemKey = (item) => item.id ?? `p${item.projected_from}-${item.due_date}`;

export const PROJECTED_HINT = 'Projected: added automatically once the current one is marked paid';

export function dueText(item) {
  if (item.paid) return 'Paid';
  const d = item.days_left;
  if (d < 0) return `${-d}d overdue`;
  if (d === 0) return 'Due today';
  if (d === 1) return 'Tomorrow';
  return `in ${d} days`;
}
