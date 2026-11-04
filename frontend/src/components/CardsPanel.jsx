import { useEffect, useState } from 'react';
import { CreditCard, Pencil, Plus, Trash2 } from 'lucide-react';
import { money, parseISO, shortDate } from '../lib/format';
import { parseAmount } from '../lib/payment';
import Modal from './Modal';

const ordinal = (n) => {
  const s = ['th', 'st', 'nd', 'rd'];
  const v = n % 100;
  return `${n}${s[(v - 20) % 10] || s[v] || s[0]}`;
};
const monthYear = (iso) => parseISO(iso).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' });

/** Credit cards: what is due now, what has built up this cycle, and EMIs still to come.
 *  Debit cards are listed by name so a payment can say which one it came from. */
export default function CardsPanel({ cards, categories, todayISO, onSaveCard, onDeleteCard, onPay, onSaveEmi, onDeleteEmi, className = '' }) {
  const [cardForm, setCardForm] = useState(null); // null | { card? }
  const [emiForm, setEmiForm] = useState(null); // null | { card, emi? }
  const [confirm, setConfirm] = useState(null); // 'card-1' | 'emi-3'

  useEffect(() => {
    if (confirm == null) return;
    const t = setTimeout(() => setConfirm(null), 4000);
    return () => clearTimeout(t);
  }, [confirm]);

  const credit = cards.filter((c) => c.kind !== 'debit');
  const debit = cards.filter((c) => c.kind === 'debit');
  const total = credit.reduce((s, c) => s + c.total_owed, 0);

  const del = (key, label, action) =>
    confirm === key ? (
      <button className="btn bg-rose-600 px-2 py-1 text-xs text-white hover:bg-rose-700" onClick={() => { setConfirm(null); action(); }}>
        Confirm delete
      </button>
    ) : (
      <button className="btn-ghost p-1.5 text-stone-500 hover:text-rose-600" onClick={() => setConfirm(key)} aria-label={`Delete ${label}`}>
        <Trash2 className="h-4 w-4" />
      </button>
    );

  return (
    <section className={`card p-5 ${className}`} aria-labelledby="cards-h">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h2 id="cards-h" className="text-base font-semibold">Cards</h2>
          <p className="num text-xs text-stone-500 dark:text-stone-400">
            {credit.length
              ? `${money(total)} owed across ${credit.length} credit card${credit.length === 1 ? '' : 's'}`
              : cards.length ? `${debit.length} debit card${debit.length === 1 ? '' : 's'}` : 'No cards yet'}
          </p>
        </div>
        <button className="btn-outline px-2.5 py-1.5 text-xs" onClick={() => setCardForm({})}>
          <Plus className="h-3.5 w-3.5" /> Card
        </button>
      </div>

      {cards.length === 0 && (
        <p className="mt-4 text-sm text-stone-500 dark:text-stone-400">
          Add your credit and debit cards, then pick the card when you add an expense. A credit card&apos;s bill is
          built from what you charge to it plus any EMIs.
        </p>
      )}

      <ul className="mt-2 space-y-4">
        {credit.map((c) => (
          <li key={c.id} data-card={c.name} className="rounded-xl border border-stone-200 p-3 dark:border-neutral-800">
            <div className="flex items-start gap-2">
              <CreditCard className="mt-0.5 h-4 w-4 shrink-0 text-stone-400" />
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{c.name}</p>
                <p className="text-xs text-stone-500 dark:text-stone-400">
                  Statement on the {ordinal(c.statement_day)} · due on the {ordinal(c.due_day)}
                </p>
              </div>
              <div className="text-right">
                <p className="num font-bold" data-testid="card-total">{money(c.total_owed)}</p>
                <p className="text-[11px] text-stone-500 dark:text-stone-400">total owed</p>
              </div>
            </div>

            <dl className="num mt-3 space-y-2 text-sm">
              {c.unpaid_statements.map((st) => (
                <div key={st.statement_date} className="flex items-center justify-between gap-2">
                  <dt className={st.overdue ? 'text-rose-600 dark:text-rose-400' : 'text-stone-600 dark:text-stone-300'}>
                    Bill due {shortDate(st.due_date)}{st.overdue && ' · overdue'}
                    <span className="block text-[11px] text-stone-500 dark:text-stone-400">
                      statement {shortDate(st.statement_date)}{st.paid > 0 && ` · ${money(st.paid)} paid`}
                    </span>
                  </dt>
                  <dd className="flex items-center gap-2 font-medium">
                    {money(st.balance)}
                    <button className="btn-outline px-2 py-1 text-xs" onClick={() => onPay(c, st)}
                      aria-label={`Pay ${c.name} bill due ${shortDate(st.due_date)}`}>
                      Pay
                    </button>
                  </dd>
                </div>
              ))}
              {c.current_statement && (
                <div className="flex items-center justify-between gap-2">
                  <dt className="text-stone-600 dark:text-stone-300">
                    This cycle so far
                    <span className="block text-[11px] text-stone-500 dark:text-stone-400">
                      statement {shortDate(c.current_statement.statement_date)} · due {shortDate(c.current_statement.due_date)}
                      {c.current_statement.total > c.charged_this_cycle && ` · about ${money(c.current_statement.total)} expected`}
                    </span>
                  </dt>
                  <dd className="font-medium">{money(c.charged_this_cycle)}</dd>
                </div>
              )}
              {c.emi_remaining > 0 && (
                <div className="flex items-center justify-between gap-2">
                  <dt className="text-stone-600 dark:text-stone-300">EMIs still to come</dt>
                  <dd className="font-medium">{money(c.emi_remaining)}</dd>
                </div>
              )}
            </dl>

            {c.emis.length > 0 && (
              <ul className="mt-3 space-y-1.5 border-t border-stone-100 pt-2 dark:border-neutral-800">
                {c.emis.map((e) => (
                  <li key={e.id} data-emi={e.name} className="flex items-center gap-2 text-sm">
                    <div className="min-w-0 flex-1">
                      <p className="truncate">{e.name} <span className="num text-stone-500 dark:text-stone-400">· {money(e.monthly_amount)}/month</span></p>
                      <p className="num text-[11px] text-stone-500 dark:text-stone-400">
                        {e.months_done} of {e.months} paid · {e.months_left ? `ends ${monthYear(e.last_date)}` : 'finished'}
                      </p>
                    </div>
                    <button className="btn-ghost p-1.5" onClick={() => setEmiForm({ card: c, emi: e })} aria-label={`Edit ${e.name} EMI`}>
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    {del(`emi-${e.id}`, `${e.name} EMI`, () => onDeleteEmi(e))}
                  </li>
                ))}
              </ul>
            )}

            <div className="mt-3 flex items-center gap-1">
              <button className="btn-outline px-2.5 py-1.5 text-xs" onClick={() => setEmiForm({ card: c })}>
                <Plus className="h-3.5 w-3.5" /> EMI
              </button>
              <button className="btn-ghost p-1.5" onClick={() => setCardForm({ card: c })} aria-label={`Edit ${c.name} card`}>
                <Pencil className="h-4 w-4" />
              </button>
              {del(`card-${c.id}`, `${c.name} card`, () => onDeleteCard(c))}
            </div>
          </li>
        ))}
      </ul>

      {debit.length > 0 && (
        <div className="mt-4">
          <p className="label">Debit cards</p>
          <ul className="divide-y divide-stone-100 rounded-xl border border-stone-200 dark:divide-neutral-800 dark:border-neutral-800">
            {debit.map((c) => (
              <li key={c.id} data-card={c.name} className="flex items-center gap-2 px-3 py-2 text-sm">
                <CreditCard className="h-4 w-4 shrink-0 text-stone-400" />
                <span className="min-w-0 flex-1 truncate">{c.name}</span>
                <button className="btn-ghost p-1.5" onClick={() => setCardForm({ card: c })} aria-label={`Edit ${c.name} card`}>
                  <Pencil className="h-4 w-4" />
                </button>
                {del(`card-${c.id}`, `${c.name} card`, () => onDeleteCard(c))}
              </li>
            ))}
          </ul>
        </div>
      )}

      {cardForm && (
        <CardForm card={cardForm.card} onClose={() => setCardForm(null)}
          onSubmit={async (payload) => { await onSaveCard(payload, cardForm.card?.id); setCardForm(null); }} />
      )}
      {emiForm && (
        <EmiForm card={emiForm.card} emi={emiForm.emi} categories={categories} todayISO={todayISO} onClose={() => setEmiForm(null)}
          onSubmit={async (payload) => { await onSaveEmi(emiForm.card, payload, emiForm.emi?.id); setEmiForm(null); }} />
      )}
    </section>
  );
}

function FormShell({ title, onClose, onSubmit, saving, error, submitLabel, children }) {
  return (
    <Modal title={title} onClose={onClose}>
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        {children}
        {error && <p role="alert" className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-950/50 dark:text-rose-300">{error}</p>}
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-outline" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={saving}>{saving ? 'Saving…' : submitLabel}</button>
        </div>
      </form>
    </Modal>
  );
}

const day = (t) => {
  const n = Number(t);
  return Number.isInteger(n) && n >= 1 && n <= 31 ? n : null;
};

function CardForm({ card, onSubmit, onClose }) {
  const [kind, setKind] = useState(card?.kind ?? 'credit');
  const [name, setName] = useState(card?.name ?? '');
  const [statementDay, setStatementDay] = useState(card ? String(card.statement_day) : '');
  const [dueDay, setDueDay] = useState(card ? String(card.due_day) : '');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!name.trim()) return setError('Give the card a name, e.g. HDFC Millennia');
    if (kind === 'credit' && (!day(statementDay) || !day(dueDay))) {
      return setError('Statement and due days are days of the month, 1 to 31');
    }
    setSaving(true);
    setError('');
    try {
      await onSubmit(kind === 'credit'
        ? { name: name.trim(), kind, statement_day: day(statementDay), due_day: day(dueDay) }
        : { name: name.trim(), kind });
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  };

  return (
    <FormShell title={card ? 'Edit card' : 'Add card'} onClose={onClose} onSubmit={submit} saving={saving}
      error={error} submitLabel={card ? 'Save changes' : 'Add card'}>
      <fieldset>
        <legend className="label">Type</legend>
        <div className="grid grid-cols-2 rounded-lg border border-stone-300 p-0.5 dark:border-neutral-700">
          {[['credit', 'Credit card'], ['debit', 'Debit card']].map(([k, label]) => (
            <button key={k} type="button" aria-pressed={kind === k} disabled={Boolean(card) && kind !== k}
              onClick={() => setKind(k)}
              className={`rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors disabled:opacity-40 ${
                kind === k
                  ? 'bg-stone-900 text-white dark:bg-stone-100 dark:text-stone-900'
                  : 'text-stone-600 hover:bg-stone-100 dark:text-stone-300 dark:hover:bg-neutral-800'
              }`}>
              {label}
            </button>
          ))}
        </div>
      </fieldset>
      <div>
        <label className="label" htmlFor="c-name">Card name</label>
        <input id="c-name" className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={40}
          placeholder={kind === 'credit' ? 'e.g. HDFC Millennia' : 'e.g. SBI Savings'} autoFocus />
      </div>
      {kind === 'debit' ? (
        <p className="text-xs text-stone-500 dark:text-stone-400">
          Debit cards have no bill: payments come straight out of your bank. Pick the card when you choose
          &ldquo;Debit card&rdquo; as the payment mode.
        </p>
      ) : (<>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="label" htmlFor="c-statement">Statement day</label>
          <input id="c-statement" className="input num" inputMode="numeric" value={statementDay}
            onChange={(e) => setStatementDay(e.target.value)} placeholder="e.g. 15" />
        </div>
        <div>
          <label className="label" htmlFor="c-due">Payment due day</label>
          <input id="c-due" className="input num" inputMode="numeric" value={dueDay}
            onChange={(e) => setDueDay(e.target.value)} placeholder="e.g. 5" />
        </div>
      </div>
      <p className="text-xs text-stone-500 dark:text-stone-400">
        Both are on your card statement. Purchases up to the statement day make one bill, due on the due day
        {day(statementDay) && day(dueDay) ? (day(dueDay) > day(statementDay) ? ' later that month' : ' the next month') : ''}.
      </p>
      </>)}
    </FormShell>
  );
}

function EmiForm({ card, emi, categories, todayISO, onSubmit, onClose }) {
  const [f, setF] = useState({
    name: emi?.name ?? '',
    category: emi?.category ?? '',
    monthly: emi ? String(emi.monthly_amount) : '',
    first: emi?.first_date ?? todayISO,
    months: emi ? String(emi.months) : '',
  });
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }));

  const monthly = parseAmount(f.monthly);
  const months = Number(f.months);
  const valid = monthly > 0 && Number.isInteger(months) && months >= 1 && months <= 360;

  const submit = async (e) => {
    e.preventDefault();
    if (!f.name.trim()) return setError('What is the EMI for?');
    if (!(monthly > 0)) return setError('Enter the monthly instalment');
    if (!f.first) return setError('Pick the date of the first instalment');
    if (!valid) return setError('Number of months must be between 1 and 360');
    setSaving(true);
    setError('');
    try {
      await onSubmit({ name: f.name.trim(), category: f.category.trim() || 'EMI', monthly_amount: monthly, first_date: f.first, months });
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  };

  const last = valid && f.first ? (() => {
    const d = parseISO(f.first);
    return new Date(d.getFullYear(), d.getMonth() + months - 1, 1).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' });
  })() : null;

  return (
    <FormShell title={emi ? 'Edit EMI' : `Add EMI on ${card.name}`} onClose={onClose} onSubmit={submit} saving={saving}
      error={error} submitLabel={emi ? 'Save changes' : 'Add EMI'}>
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className="label" htmlFor="e-name">EMI for</label>
          <input id="e-name" className="input" value={f.name} onChange={set('name')} maxLength={80} placeholder="e.g. iPhone" autoFocus />
        </div>
        <div>
          <label className="label" htmlFor="e-cat">Category</label>
          <input id="e-cat" className="input" list="emi-categories" value={f.category} onChange={set('category')}
            maxLength={60} placeholder="e.g. Electronics" autoComplete="off" />
          <datalist id="emi-categories">{categories.map((c) => <option key={c} value={c} />)}</datalist>
        </div>
        <div>
          <label className="label" htmlFor="e-monthly">Monthly instalment (₹)</label>
          <input id="e-monthly" className="input num" inputMode="decimal" value={f.monthly} onChange={set('monthly')} placeholder="0.00" />
        </div>
        <div>
          <label className="label" htmlFor="e-months">Number of months</label>
          <input id="e-months" className="input num" inputMode="numeric" value={f.months} onChange={set('months')} placeholder="e.g. 12" />
        </div>
        <div>
          <label className="label" htmlFor="e-first">First instalment on</label>
          <input id="e-first" type="date" className="input" value={f.first} onChange={set('first')} />
        </div>
      </div>
      {last && (
        <p className="num text-xs text-stone-500 dark:text-stone-400">
          {months} × {money(monthly)} = {money(months * monthly)}, last instalment in {last}. Each instalment is added to
          that month&apos;s {card.name} bill and counts as spending in its category.
        </p>
      )}
    </FormShell>
  );
}
