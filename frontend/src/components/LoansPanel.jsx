import { useEffect, useState } from 'react';
import { BellRing, HandCoins, Pencil, Plus, Trash2, Undo2 } from 'lucide-react';
import { money, shortDate } from '../lib/format';
import { parseAmount } from '../lib/payment';
import Modal from './Modal';

const REMIND = [
  ['', 'No reminders'],
  ['1', 'Every day'],
  ['3', 'Every 3 days'],
  ['7', 'Every week'],
  ['14', 'Every 2 weeks'],
  ['30', 'Every month'],
];
const everyText = (n) => (REMIND.find(([k]) => k === String(n))?.[1] ?? `Every ${n} days`).toLowerCase();

function dueChip(l) {
  if (!l.due_date) return null;
  if (l.overdue) return { text: `${-l.days_to_due}d past due`, cls: 'bg-rose-600 text-white' };
  if (l.days_to_due === 0) return { text: 'Due back today', cls: 'bg-amber-100 text-amber-900 dark:bg-amber-900/50 dark:text-amber-100' };
  return { text: `Due back ${shortDate(l.due_date)}`, cls: 'bg-stone-100 text-stone-700 dark:bg-neutral-800 dark:text-stone-300' };
}

/** Money you lent: what is still owed, by when, and reminders to ask for it back. */
export default function LoansPanel({ loans, todayISO, onSave, onDelete, onRepay, onUndoRepay, onReminded, className = '' }) {
  const [form, setForm] = useState(null); // null | { loan? }
  const [repaying, setRepaying] = useState(null);
  const [confirmId, setConfirmId] = useState(null);
  const [showRepaid, setShowRepaid] = useState(false);

  useEffect(() => {
    if (confirmId == null) return;
    const t = setTimeout(() => setConfirmId(null), 4000);
    return () => clearTimeout(t);
  }, [confirmId]);

  const open = loans.filter((l) => l.status === 'open');
  const repaid = loans.filter((l) => l.status === 'repaid');
  const owed = open.reduce((s, l) => s + l.outstanding, 0);
  // keep the repayment dialog in sync with fresh data after each change
  const repayLoan = repaying && loans.find((l) => l.id === repaying);

  const row = (l) => {
    const chip = dueChip(l);
    return (
      <li key={l.id} data-loan={l.person} className="py-3">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <p className="truncate font-medium">{l.person}</p>
            <p className="num text-xs text-stone-500 dark:text-stone-400">
              {l.status === 'repaid'
                ? `${money(l.amount)} repaid in full`
                : l.repaid > 0
                  ? `${money(l.outstanding)} left of ${money(l.amount)}`
                  : `Lent ${shortDate(l.lent_on)}`}
              {l.note && ` · ${l.note}`}
            </p>
          </div>
          <span className="num shrink-0 font-semibold">{money(l.status === 'repaid' ? l.amount : l.outstanding)}</span>
        </div>

        {l.status === 'open' && (
          <>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-stone-500 dark:text-stone-400">
              {chip && <span className={`rounded-full px-2 py-0.5 font-medium ${chip.cls}`}>{chip.text}</span>}
              {l.remind_every_days && !l.reminder_due && l.next_remind_on && (
                <span>Next reminder {shortDate(l.next_remind_on)} · {everyText(l.remind_every_days)}</span>
              )}
            </div>
            {l.reminder_due && (
              <div role="status" className="mt-2 flex flex-wrap items-center justify-between gap-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-950/40 dark:text-amber-100">
                <span className="flex items-center gap-1.5">
                  <BellRing className="h-4 w-4" /> Time to ask {l.person} for {money(l.outstanding)}
                </span>
                <button className="btn-outline border-current/30 px-2 py-1 text-xs" onClick={() => onReminded(l)}>
                  I&apos;ve asked
                </button>
              </div>
            )}
            <div className="mt-2 flex items-center gap-1">
              <button className="btn-outline px-2.5 py-1.5 text-xs" onClick={() => setRepaying(l.id)}>
                <HandCoins className="h-3.5 w-3.5" /> Got money back
              </button>
              <button className="btn-ghost p-1.5" onClick={() => setForm({ loan: l })} aria-label={`Edit loan to ${l.person}`}>
                <Pencil className="h-4 w-4" />
              </button>
              {confirmId === l.id ? (
                <button className="btn bg-rose-600 px-2 py-1 text-xs text-white hover:bg-rose-700"
                  onClick={() => { setConfirmId(null); onDelete(l); }}>
                  Confirm delete
                </button>
              ) : (
                <button className="btn-ghost p-1.5 text-stone-500 hover:text-rose-600" onClick={() => setConfirmId(l.id)}
                  aria-label={`Delete loan to ${l.person}`}>
                  <Trash2 className="h-4 w-4" />
                </button>
              )}
            </div>
          </>
        )}
      </li>
    );
  };

  return (
    <section className={`card p-5 ${className}`} aria-labelledby="loans-h">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h2 id="loans-h" className="text-base font-semibold">Money lent</h2>
          <p className="num text-xs text-stone-500 dark:text-stone-400">
            {open.length ? `${money(owed)} owed to you by ${open.length} ${open.length === 1 ? 'person' : 'people'}` : 'Nobody owes you money'}
          </p>
        </div>
        <button className="btn-outline px-2.5 py-1.5 text-xs" onClick={() => setForm({})}>
          <Plus className="h-3.5 w-3.5" /> Lend
        </button>
      </div>

      {open.length === 0 && repaid.length === 0 ? (
        <p className="mt-4 text-sm text-stone-500 dark:text-stone-400">
          Record money you lend so you know who owes you, and get reminded to ask for it back.
        </p>
      ) : (
        <ul className="mt-2 divide-y divide-stone-100 dark:divide-neutral-800">{open.map(row)}</ul>
      )}

      {repaid.length > 0 && (
        <div className="mt-2 border-t border-stone-100 pt-2 dark:border-neutral-800">
          <button className="text-xs text-stone-500 underline-offset-2 hover:underline dark:text-stone-400"
            aria-expanded={showRepaid} onClick={() => setShowRepaid((v) => !v)}>
            {showRepaid ? 'Hide' : 'Show'} repaid ({repaid.length})
          </button>
          {showRepaid && <ul className="divide-y divide-stone-100 opacity-75 dark:divide-neutral-800">{repaid.map(row)}</ul>}
        </div>
      )}

      {form && (
        <LoanForm loan={form.loan} todayISO={todayISO} onClose={() => setForm(null)}
          onSubmit={async (payload) => { await onSave(payload, form.loan?.id); setForm(null); }} />
      )}
      {repayLoan && (
        <RepayForm loan={repayLoan} todayISO={todayISO} onClose={() => setRepaying(null)} onUndo={onUndoRepay}
          onSubmit={async (body) => { await onRepay(repayLoan, body); setRepaying(null); }} />
      )}
    </section>
  );
}

function LoanForm({ loan, todayISO, onSubmit, onClose }) {
  const [f, setF] = useState({
    person: loan?.person ?? '',
    amount: loan ? String(loan.amount) : '',
    lent_on: loan?.lent_on ?? todayISO,
    due_date: loan?.due_date ?? '',
    note: loan?.note ?? '',
    remind: loan?.remind_every_days ? String(loan.remind_every_days) : '7',
    first: '',
  });
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    const amount = parseAmount(f.amount);
    const next = {};
    if (!f.person.trim()) next.person = 'Who did you lend it to?';
    if (!(amount > 0)) next.amount = 'Enter an amount greater than 0';
    if (!f.lent_on) next.lent_on = 'Pick the date you lent it';
    if (f.due_date && f.lent_on && f.due_date < f.lent_on) next.due_date = 'Cannot be before you lent it';
    setErrors(next);
    if (Object.keys(next).length) return;
    setSaving(true);
    setFormError('');
    try {
      await onSubmit({
        person: f.person.trim(), amount, lent_on: f.lent_on, due_date: f.due_date || null, note: f.note.trim() || null,
        remind_every_days: f.remind ? Number(f.remind) : null, first_reminder_on: (f.remind && f.first) || null,
      });
    } catch (err) {
      setFormError(err.message);
      setSaving(false);
    }
  };

  const err = (k) => errors[k] && <p id={`l-${k}-err`} className="mt-1 text-xs text-rose-600 dark:text-rose-400">{errors[k]}</p>;
  const aria = (k) => ({ 'aria-invalid': Boolean(errors[k]), 'aria-describedby': errors[k] ? `l-${k}-err` : undefined });
  const firstHint = f.due_date ? `the day it's due back (${shortDate(f.due_date)})` : 'one interval after you lent it';

  return (
    <Modal title={loan ? 'Edit loan' : 'Lend money'} onClose={onClose}>
      <form onSubmit={submit} noValidate className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="l-person">Lent to</label>
            <input id="l-person" className="input" value={f.person} onChange={set('person')} maxLength={80}
              placeholder="e.g. Rahul" autoFocus {...aria('person')} />
            {err('person')}
          </div>
          <div>
            <label className="label" htmlFor="l-amount">Amount (₹)</label>
            <input id="l-amount" className="input num" inputMode="decimal" value={f.amount} onChange={set('amount')}
              placeholder="0.00" {...aria('amount')} />
            {err('amount')}
          </div>
          <div>
            <label className="label" htmlFor="l-lent">Lent on</label>
            <input id="l-lent" type="date" className="input" value={f.lent_on} onChange={set('lent_on')} {...aria('lent_on')} />
            {err('lent_on')}
          </div>
          <div>
            <label className="label" htmlFor="l-due">Get it back by (optional)</label>
            <input id="l-due" type="date" className="input" value={f.due_date} onChange={set('due_date')} {...aria('due_date')} />
            {err('due_date')}
          </div>
        </div>
        <div>
          <label className="label" htmlFor="l-note">Note (optional)</label>
          <input id="l-note" className="input" value={f.note} onChange={set('note')} maxLength={200} placeholder="e.g. Goa trip" />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="l-remind">Remind me to ask</label>
            <select id="l-remind" className="input" value={f.remind} onChange={set('remind')}>
              {REMIND.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
            </select>
          </div>
          {f.remind && (
            <div>
              <label className="label" htmlFor="l-first">First reminder on (optional)</label>
              <input id="l-first" type="date" className="input" value={f.first} onChange={set('first')} />
            </div>
          )}
        </div>
        {f.remind && (
          <p className="-mt-2 text-xs text-stone-500 dark:text-stone-400">
            Starts {f.first ? shortDate(f.first) : firstHint}, then {everyText(f.remind)} until it&apos;s repaid.
            Reminders show here and as a browser notification while the app is open.
          </p>
        )}
        {formError && <p role="alert" className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-950/50 dark:text-rose-300">{formError}</p>}
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-outline" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={saving}>{saving ? 'Saving…' : loan ? 'Save changes' : 'Save loan'}</button>
        </div>
      </form>
    </Modal>
  );
}

function RepayForm({ loan, todayISO, onSubmit, onUndo, onClose }) {
  const [amount, setAmount] = useState(String(loan.outstanding));
  const [paidOn, setPaidOn] = useState(todayISO);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    const n = parseAmount(amount);
    if (!(n > 0)) return setError('Enter an amount greater than 0');
    if (n > loan.outstanding + 0.005) return setError(`Only ${money(loan.outstanding)} is still owed`);
    setSaving(true);
    setError('');
    try {
      await onSubmit({ amount: n, paid_on: paidOn || todayISO });
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  };

  return (
    <Modal title={`Money back from ${loan.person}`} onClose={onClose}>
      <form onSubmit={submit} noValidate className="space-y-4">
        <p className="num text-sm text-stone-600 dark:text-stone-300">
          {money(loan.outstanding)} still owed of {money(loan.amount)}.
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="r-amount">Amount received (₹)</label>
            <input id="r-amount" className="input num" inputMode="decimal" value={amount} autoFocus
              onChange={(e) => setAmount(e.target.value)} />
          </div>
          <div>
            <label className="label" htmlFor="r-date">Received on</label>
            <input id="r-date" type="date" className="input" value={paidOn} onChange={(e) => setPaidOn(e.target.value)} />
          </div>
        </div>
        {loan.repayments.length > 0 && (
          <div>
            <p className="label">Received so far</p>
            <ul className="num divide-y divide-stone-100 text-sm dark:divide-neutral-800">
              {loan.repayments.map((r) => (
                <li key={r.id} className="flex items-center justify-between py-1.5">
                  <span>{shortDate(r.paid_on)}</span>
                  <span className="flex items-center gap-1">
                    {money(r.amount)}
                    <button type="button" className="btn-ghost p-1" onClick={() => onUndo(loan, r)}
                      aria-label={`Remove ${money(r.amount)} repayment`} title="Remove">
                      <Undo2 className="h-3.5 w-3.5" />
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {error && <p role="alert" className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-950/50 dark:text-rose-300">{error}</p>}
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-outline" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Record repayment'}</button>
        </div>
      </form>
    </Modal>
  );
}
