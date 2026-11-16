import { useEffect, useState } from 'react';
import { ChevronDown, Pencil, Plus, Target, Trash2 } from 'lucide-react';
import { api } from '../lib/api';
import { money, parseISO } from '../lib/format';
import { parseAmount } from '../lib/payment';
import Modal from './Modal';
import SpendingChart from './SpendingChart';

const monthYear = (iso) => parseISO(iso).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' });

/** Goals bigger than a month (a house, a car): what is planned, what has gone on it so far, and
 *  where it went. Expenses tagged with a goal stay out of the monthly budget. */
export default function GoalsPanel({ goals, onSave, onDelete, onAddExpense, onEditExpense, className = '' }) {
  const [form, setForm] = useState(null); // null | { goal? }
  const [openId, setOpenId] = useState(null);
  const [confirmId, setConfirmId] = useState(null);

  useEffect(() => {
    if (confirmId == null) return;
    const t = setTimeout(() => setConfirmId(null), 4000);
    return () => clearTimeout(t);
  }, [confirmId]);

  const planned = goals.reduce((s, g) => s + g.budget, 0);
  const spent = goals.reduce((s, g) => s + g.spent, 0);

  return (
    <section className={`card p-5 ${className}`} aria-labelledby="goals-h">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h2 id="goals-h" className="text-base font-semibold">Goals</h2>
          <p className="num text-xs text-stone-500 dark:text-stone-400">
            {goals.length ? `${money(spent)} spent of ${money(planned)} planned` : 'Kept out of your monthly budget'}
          </p>
        </div>
        <button className="btn-outline px-2.5 py-1.5 text-xs" onClick={() => setForm({})}>
          <Plus className="h-3.5 w-3.5" /> Goal
        </button>
      </div>

      {goals.length === 0 ? (
        <p className="mt-4 text-sm text-stone-500 dark:text-stone-400">
          Add a goal like building a house, set what you plan to spend on it, then tag its expenses with it.
          They count towards the goal instead of turning your month red.
        </p>
      ) : (
        <ul className="mt-2 divide-y divide-stone-100 dark:divide-neutral-800">
          {goals.map((g) => {
            const over = g.left < 0;
            const share = Math.min(g.spent / g.budget, 1);
            const expanded = openId === g.id;
            return (
              <li key={g.id} data-goal={g.name} className="py-3">
                <div className="flex items-baseline justify-between gap-3">
                  <p className="flex min-w-0 items-center gap-1.5 font-medium">
                    <Target className="h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
                    <span className="truncate">{g.name}</span>
                  </p>
                  <span className={`num shrink-0 text-sm font-semibold ${over ? 'text-rose-600 dark:text-rose-400' : ''}`}>
                    {over ? `${money(-g.left)} over` : `${money(g.left)} left`}
                  </span>
                </div>
                <div className="mt-1.5 h-2 rounded-full bg-stone-100 dark:bg-neutral-800"
                  role="meter" aria-valuemin={0} aria-valuemax={g.budget} aria-valuenow={g.spent}
                  aria-label={`${g.name}: ${money(g.spent)} of ${money(g.budget)}`}>
                  <div className={`h-full rounded-full ${over ? 'bg-rose-500' : 'bg-emerald-500'}`}
                    style={{ width: `${share * 100}%` }} />
                </div>
                <p className="num mt-1 text-xs text-stone-500 dark:text-stone-400">
                  {money(g.spent)} of {money(g.budget)}
                  {g.spent > g.paid && ` · ${money(g.spent - g.paid)} still to pay`}
                  {g.target_date && ` · by ${monthYear(g.target_date)}`}
                </p>
                <div className="mt-2 flex flex-wrap items-center gap-1">
                  <button className="btn-outline px-2.5 py-1.5 text-xs" onClick={() => onAddExpense(g)}>
                    <Plus className="h-3.5 w-3.5" /> Expense
                  </button>
                  {g.count > 0 && (
                    <button className="btn-ghost px-2 py-1.5 text-xs" aria-expanded={expanded}
                      onClick={() => setOpenId(expanded ? null : g.id)}>
                      {g.count} expense{g.count === 1 ? '' : 's'}
                      <ChevronDown className={`h-3.5 w-3.5 transition-transform ${expanded ? 'rotate-180' : ''}`} />
                    </button>
                  )}
                  <span className="flex-1" />
                  <button className="btn-ghost p-1.5" onClick={() => setForm({ goal: g })} aria-label={`Edit goal ${g.name}`}>
                    <Pencil className="h-4 w-4" />
                  </button>
                  {confirmId === g.id ? (
                    <button className="btn bg-rose-600 px-2 py-1 text-xs text-white hover:bg-rose-700"
                      onClick={() => { setConfirmId(null); onDelete(g); }}>
                      Confirm delete
                    </button>
                  ) : (
                    <button className="btn-ghost p-1.5 text-stone-500 hover:text-rose-600" onClick={() => setConfirmId(g.id)}
                      aria-label={`Delete goal ${g.name}`}>
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </div>
                {confirmId === g.id && (
                  <p className="mt-1 text-xs text-stone-500 dark:text-stone-400">
                    Its expenses are kept and count in their own months again.
                  </p>
                )}
                {expanded && <GoalBreakdown goal={g} onEdit={onEditExpense} />}
              </li>
            );
          })}
        </ul>
      )}

      {form && (
        <GoalForm goal={form.goal} onClose={() => setForm(null)}
          onSubmit={async (payload) => { await onSave(payload, form.goal?.id); setForm(null); }} />
      )}
    </section>
  );
}

/** Where a goal's money went, by category, across every month. Reloads whenever the goal changes. */
function GoalBreakdown({ goal, onEdit }) {
  const [items, setItems] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let stale = false;
    api.goalExpenses(goal.id)
      .then((rows) => { if (!stale) setItems(rows); })
      .catch((e) => { if (!stale) setError(e.message); });
    return () => { stale = true; };
  }, [goal]);

  if (error) return <p role="alert" className="mt-2 text-sm text-rose-600 dark:text-rose-400">{error}</p>;
  if (!items) return <p className="mt-2 text-xs text-stone-500" role="status">Loading…</p>;
  return (
    <div className="mt-3 rounded-xl bg-stone-50 p-3 dark:bg-neutral-800/50">
      <SpendingChart expenses={items} onEdit={onEdit} label={`${goal.name} by category`}
        emptyText="Nothing spent on this goal yet." />
    </div>
  );
}

function GoalForm({ goal, onSubmit, onClose }) {
  const [f, setF] = useState({
    name: goal?.name ?? '',
    budget: goal ? String(goal.budget) : '',
    target_date: goal?.target_date ?? '',
  });
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    const budget = parseAmount(f.budget);
    const next = {};
    if (!f.name.trim()) next.name = 'Name the goal';
    if (!(budget > 0)) next.budget = 'Enter what you plan to spend, more than 0';
    setErrors(next);
    if (Object.keys(next).length) return;
    setSaving(true);
    setFormError('');
    try {
      await onSubmit({ name: f.name.trim(), budget, target_date: f.target_date || null });
    } catch (err) {
      setFormError(err.message);
      setSaving(false);
    }
  };

  const err = (k) => errors[k] && <p id={`g-${k}-err`} className="mt-1 text-xs text-rose-600 dark:text-rose-400">{errors[k]}</p>;
  const aria = (k) => ({ 'aria-invalid': Boolean(errors[k]), 'aria-describedby': errors[k] ? `g-${k}-err` : undefined });

  return (
    <Modal title={goal ? 'Edit goal' : 'New goal'} onClose={onClose}>
      <form onSubmit={submit} noValidate className="space-y-4">
        <div>
          <label className="label" htmlFor="g-name">Goal</label>
          <input id="g-name" className="input" value={f.name} onChange={set('name')} maxLength={80}
            placeholder="e.g. Build house" autoFocus {...aria('name')} />
          {err('name')}
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="g-budget">Planned spending (₹)</label>
            <input id="g-budget" className="input num" inputMode="decimal" value={f.budget} onChange={set('budget')}
              placeholder="e.g. 2000000" {...aria('budget')} />
            {err('budget')}
          </div>
          <div>
            <label className="label" htmlFor="g-date">Target date (optional)</label>
            <input id="g-date" type="date" className="input" value={f.target_date} onChange={set('target_date')} />
          </div>
        </div>
        {formError && (
          <p role="alert" className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-950/50 dark:text-rose-300">
            {formError}
          </p>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-outline" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={saving}>
            {saving ? 'Saving…' : goal ? 'Save changes' : 'Add goal'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
