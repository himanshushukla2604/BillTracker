import { useEffect, useRef, useState } from 'react';
import Modal from './Modal';

const RECURRING = [
  ['none', 'One-time'],
  ['weekly', 'Weekly'],
  ['monthly', 'Monthly'],
  ['quarterly', 'Quarterly'],
  ['yearly', 'Yearly'],
];

export default function ExpenseForm({ expense, categories, todayISO, onSubmit, onClose }) {
  const editing = Boolean(expense);
  const [f, setF] = useState({
    name: expense?.name ?? '',
    amount: expense ? String(expense.amount) : '',
    due_date: expense?.due_date ?? todayISO,
    category: expense?.category ?? '',
    recurring: expense?.recurring ?? 'monthly',
  });
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);
  const nameRef = useRef(null);

  useEffect(() => { nameRef.current?.focus(); }, []);

  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    const amount = Number(f.amount.replace(/[,\s₹]/g, ''));
    const next = {};
    if (!f.name.trim()) next.name = 'Give this expense a name';
    if (!f.amount.trim() || !Number.isFinite(amount) || amount <= 0) next.amount = 'Enter an amount greater than 0';
    if (!f.due_date) next.due_date = 'Pick a due date';
    if (!f.category.trim()) next.category = 'Choose or type a category';
    setErrors(next);
    if (Object.keys(next).length) return;

    setSaving(true);
    setFormError('');
    try {
      await onSubmit(
        { name: f.name.trim(), amount, due_date: f.due_date, category: f.category.trim(), recurring: f.recurring },
        expense?.id,
      );
    } catch (err) {
      setFormError(err.message);
      setSaving(false);
    }
  };

  const err = (k) =>
    errors[k] && <p id={`${k}-err`} className="mt-1 text-xs text-rose-600 dark:text-rose-400">{errors[k]}</p>;
  const aria = (k) => ({ 'aria-invalid': Boolean(errors[k]), 'aria-describedby': errors[k] ? `${k}-err` : undefined });

  return (
    <Modal title={editing ? 'Edit expense' : 'Add expense'} onClose={onClose}>
      <form onSubmit={submit} noValidate className="space-y-4">
        <div>
          <label className="label" htmlFor="f-name">Expense name</label>
          <input id="f-name" ref={nameRef} className="input" value={f.name} onChange={set('name')}
            placeholder="e.g. JioAirFiber" maxLength={120} {...aria('name')} />
          {err('name')}
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="f-amount">Amount (₹)</label>
            <input id="f-amount" className="input num" inputMode="decimal" value={f.amount}
              onChange={set('amount')} placeholder="0.00" {...aria('amount')} />
            {err('amount')}
          </div>
          <div>
            <label className="label" htmlFor="f-due">Due date</label>
            <input id="f-due" type="date" className="input" value={f.due_date} onChange={set('due_date')} {...aria('due_date')} />
            {err('due_date')}
          </div>
        </div>

        <div>
          <label className="label" htmlFor="f-cat">Category</label>
          <input id="f-cat" className="input" list="category-options" value={f.category} onChange={set('category')}
            placeholder="Pick one or type a new category" maxLength={60} autoComplete="off" {...aria('category')} />
          <datalist id="category-options">
            {categories.map((c) => <option key={c} value={c} />)}
          </datalist>
          {err('category')}
        </div>

        <fieldset>
          <legend className="label">Repeats</legend>
          <div className="flex flex-wrap gap-2">
            {RECURRING.map(([value, label]) => (
              <label key={value} className="cursor-pointer">
                <input type="radio" name="recurring" value={value} checked={f.recurring === value}
                  onChange={set('recurring')} className="peer sr-only" />
                <span className="inline-block rounded-lg border border-stone-300 px-3 py-1.5 text-sm text-stone-700 transition-colors
                  hover:bg-stone-100 peer-checked:border-emerald-600 peer-checked:bg-emerald-50 peer-checked:font-medium peer-checked:text-emerald-800
                  peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-emerald-500
                  dark:border-neutral-700 dark:text-stone-300 dark:hover:bg-neutral-800
                  dark:peer-checked:border-emerald-500 dark:peer-checked:bg-emerald-950 dark:peer-checked:text-emerald-200">
                  {label}
                </span>
              </label>
            ))}
          </div>
          {f.recurring !== 'none' && (
            <p className="mt-2 text-xs text-stone-500 dark:text-stone-400">
              When you mark it paid, the next {f.recurring === 'weekly' ? 'week' : f.recurring.replace('ly', '')}'s bill is created automatically.
            </p>
          )}
        </fieldset>

        {formError && (
          <p role="alert" className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-950/50 dark:text-rose-300">
            {formError}
          </p>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-outline" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={saving}>
            {saving ? 'Saving…' : editing ? 'Save changes' : 'Add expense'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
