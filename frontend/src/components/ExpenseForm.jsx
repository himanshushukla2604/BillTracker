import { useEffect, useRef, useState } from 'react';
import { money } from '../lib/format';
import { PAYMENT_MODES, cardKindFor } from '../lib/payment';
import Modal from './Modal';

const RECURRING = [
  ['none', 'One-time'],
  ['weekly', 'Weekly'],
  ['monthly', 'Monthly'],
  ['quarterly', 'Quarterly'],
  ['yearly', 'Yearly'],
];

export default function ExpenseForm({ expense, categories, cards = [], todayISO, onSubmit, onClose }) {
  const editing = Boolean(expense);
  const [f, setF] = useState({
    name: expense?.name ?? '',
    amount: expense ? String(expense.amount) : '',
    due_date: expense?.due_date ?? todayISO,
    category: expense?.category ?? '',
    recurring: expense?.recurring ?? 'monthly',
    reimbursed: expense?.reimbursed ? String(expense.reimbursed) : '',
    reimbursed_note: expense?.reimbursed_note ?? '',
    payment_mode: expense?.payment_mode ?? '',
    card_id: expense?.card_id != null ? String(expense.card_id) : '',
  });
  const kind = cardKindFor(f.payment_mode);
  const choices = cards.filter((c) => c.kind === kind);
  // a credit card must be chosen, so default to the first; a debit card is optional
  const cardId = f.card_id && choices.some((c) => String(c.id) === f.card_id)
    ? f.card_id
    : kind === 'credit' && choices[0] ? String(choices[0].id) : '';
  const [showBack, setShowBack] = useState(Boolean(expense?.reimbursed));
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);
  const nameRef = useRef(null);

  useEffect(() => { nameRef.current?.focus(); }, []);

  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    const amount = Number(f.amount.replace(/[,\s₹]/g, ''));
    const backText = showBack ? f.reimbursed.replace(/[,\s₹]/g, '') : '';
    const reimbursed = backText === '' ? 0 : Number(backText);
    const next = {};
    if (!f.name.trim()) next.name = 'Give this expense a name';
    if (!f.amount.trim() || !Number.isFinite(amount) || amount <= 0) next.amount = 'Enter an amount greater than 0';
    if (!f.due_date) next.due_date = 'Pick a due date';
    if (!f.category.trim()) next.category = 'Choose or type a category';
    if (!Number.isFinite(reimbursed) || reimbursed < 0) next.reimbursed = 'Enter 0 or more';
    else if (Number.isFinite(amount) && reimbursed > amount) next.reimbursed = 'Cannot be more than the amount';
    if (kind === 'credit' && !cardId) next.card_id = 'Add a credit card in the Cards panel first';
    setErrors(next);
    if (Object.keys(next).length) return;

    setSaving(true);
    setFormError('');
    try {
      await onSubmit(
        {
          name: f.name.trim(), amount, due_date: f.due_date, category: f.category.trim(), recurring: f.recurring,
          ...(reimbursed > 0 ? { reimbursed, reimbursed_note: f.reimbursed_note.trim() || null } : {}),
          payment_mode: f.payment_mode || null,
          card_id: kind && cardId ? Number(cardId) : null,
        },
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

        {showBack ? (
          <fieldset className="rounded-xl border border-sky-200 bg-sky-50/60 p-3 dark:border-sky-900 dark:bg-sky-950/30">
            <legend className="px-1 text-xs font-medium text-sky-800 dark:text-sky-300">Paid back to you</legend>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="label" htmlFor="f-back">Amount paid back (₹)</label>
                <input id="f-back" className="input num" inputMode="decimal" value={f.reimbursed}
                  onChange={set('reimbursed')} placeholder="0.00" {...aria('reimbursed')} />
                {err('reimbursed')}
              </div>
              <div>
                <label className="label" htmlFor="f-back-note">From / for (optional)</label>
                <input id="f-back-note" className="input" value={f.reimbursed_note} onChange={set('reimbursed_note')}
                  placeholder="e.g. Rahul, flight tickets" maxLength={120} />
              </div>
            </div>
            <div className="mt-2 flex items-center justify-between gap-2 text-xs text-sky-900/80 dark:text-sky-200/80">
              <span className="num">
                {(() => {
                  const a = Number(f.amount.replace(/[,\s₹]/g, ''));
                  const b = Number(f.reimbursed.replace(/[,\s₹]/g, '') || 0);
                  return Number.isFinite(a) && a > 0 && Number.isFinite(b) && b >= 0 && b <= a
                    ? `Counts as ${money(a - b)} of your own spending; the full bill still shows as due.`
                    : 'Only your own share counts against your budget.';
                })()}
              </span>
              <button type="button" className="shrink-0 underline underline-offset-2"
                onClick={() => { setShowBack(false); setErrors((e) => ({ ...e, reimbursed: undefined })); }}>
                Remove
              </button>
            </div>
          </fieldset>
        ) : (
          <button type="button" className="text-sm font-medium text-sky-700 underline-offset-2 hover:underline dark:text-sky-400"
            onClick={() => setShowBack(true)}>
            + Someone paid me back part of this
          </button>
        )}

        <div>
          <label className="label" htmlFor="f-cat">Category</label>
          <input id="f-cat" className="input" list="category-options" value={f.category} onChange={set('category')}
            placeholder="Pick one or type a new category" maxLength={60} autoComplete="off" {...aria('category')} />
          <datalist id="category-options">
            {categories.map((c) => <option key={c} value={c} />)}
          </datalist>
          {err('category')}
          <div className="mt-2 flex flex-wrap gap-1.5" role="group" aria-label="Suggested categories">
            {categories.map((c) => {
              const on = c.toLowerCase() === f.category.trim().toLowerCase();
              return (
                <button key={c} type="button" aria-pressed={on} onClick={() => setF((s) => ({ ...s, category: c }))}
                  className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${
                    on
                      ? 'border-emerald-600 bg-emerald-50 font-medium text-emerald-800 dark:border-emerald-500 dark:bg-emerald-950 dark:text-emerald-200'
                      : 'border-stone-300 text-stone-600 hover:bg-stone-100 dark:border-neutral-700 dark:text-stone-300 dark:hover:bg-neutral-800'
                  }`}>
                  {c}
                </button>
              );
            })}
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="f-mode">Paid with</label>
            <select id="f-mode" className="input" value={f.payment_mode} onChange={set('payment_mode')}>
              <option value="">Not set</option>
              {PAYMENT_MODES.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
            </select>
          </div>
          {kind && (
            <div>
              <label className="label" htmlFor="f-card">Card</label>
              <select id="f-card" className="input" value={cardId} onChange={set('card_id')} {...aria('card_id')}
                disabled={kind === 'credit' && !choices.length}>
                {kind === 'debit' && <option value="">{choices.length ? 'Not saying' : 'No debit cards added'}</option>}
                {kind === 'credit' && !choices.length && <option value="">No credit cards yet</option>}
                {choices.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              {err('card_id')}
            </div>
          )}
        </div>
        {kind === 'credit' && choices.length > 0 && (
          <p className="-mt-2 text-xs text-stone-500 dark:text-stone-400">
            Counts as spending on its date and goes on that card&apos;s bill, so it isn&apos;t a separate bill to pay.
          </p>
        )}

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
