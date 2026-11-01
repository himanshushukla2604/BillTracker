import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, Moon, Plus, Sun, CheckCheck } from 'lucide-react';
import { api } from './lib/api';
import { ALERT_DAYS, computeVariance, summarize } from './lib/calc';
import { daysInMonth, localISO, monthLabel, parseISO, shiftMonth } from './lib/format';
import { useTheme } from './lib/theme';
import AlertBanner from './components/AlertBanner';
import BudgetsModal from './components/BudgetsModal';
import ExpenseForm from './components/ExpenseForm';
import ExpenseList from './components/ExpenseList';
import SummaryWidget from './components/SummaryWidget';
import Toast from './components/Toast';
import UpcomingTimeline from './components/UpcomingTimeline';
import VarianceModule from './components/VarianceModule';

const EMPTY = { expenses: [], upcoming: [], budgets: [], categories: [] };

export default function App() {
  const [dark, toggleTheme] = useTheme();
  const todayISO = localISO();
  const currentMonth = todayISO.slice(0, 7);

  const [month, setMonth] = useState(currentMonth);
  const [days, setDays] = useState(30);
  const [data, setData] = useState(EMPTY);
  const [totalBudget, setTotalBudget] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(null);
  const [form, setForm] = useState(null); // null | { expense?: Expense }
  const [showTargets, setShowTargets] = useState(false);
  const [toast, setToast] = useState(null);

  const budgetTimer = useRef(null);
  const budgetDirty = useRef(false);

  const refresh = useCallback(async () => {
    try {
      const [expenses, upcoming, budgets, settings, categories] = await Promise.all([
        api.expenses(month), api.upcoming(Math.max(days, 7)), api.budgets(), api.settings(), api.categories(),
      ]);
      setData({ expenses, upcoming, budgets, categories });
      if (!budgetDirty.current) setTotalBudget(settings.total_budget);
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoaded(true);
    }
  }, [month, days]);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => () => clearTimeout(budgetTimer.current), []);

  // ---- derived, recalculated instantly on every change
  const summary = useMemo(() => summarize(data.expenses, totalBudget), [data.expenses, totalBudget]);
  const variance = useMemo(() => computeVariance(data.expenses, data.budgets), [data.expenses, data.budgets]);

  const overdue = useMemo(() => data.upcoming.filter((i) => i.urgency === 'overdue'), [data.upcoming]);
  const dueSoon = useMemo(
    () => data.upcoming.filter((i) => (i.urgency === 'urgent' || i.urgency === 'soon') && i.days_left <= ALERT_DAYS),
    [data.upcoming],
  );

  useEffect(() => {
    const n = overdue.length + dueSoon.length;
    document.title = n ? `(${n}) Bill Tracker` : 'Bill Tracker';
  }, [overdue.length, dueSoon.length]);

  const isCurrentMonth = month === currentMonth;
  const daysLeft = isCurrentMonth ? daysInMonth(month) - Number(todayISO.slice(8)) + 1 : null;
  const perDay = daysLeft && summary.remaining > 0 ? summary.remaining / daysLeft : null;
  const label = monthLabel(month);

  // ---- actions
  const run = async (fn, msg, undo) => {
    try {
      await fn();
      await refresh();
      if (msg) setToast({ msg, undo });
    } catch (e) {
      setToast({ msg: e.message, error: true });
    }
  };

  const undoPay = (e) => async () => { await run(() => api.unpay(e.id), null); };
  const pay = (e) =>
    run(() => api.pay(e.id), `${e.name} marked paid${e.recurring !== 'none' ? ' · next one scheduled' : ''}`, undoPay(e));
  const unpay = (e) => run(() => api.unpay(e.id), `${e.name} marked unpaid`);
  const remove = (e) => run(() => api.remove(e.id), `${e.name} deleted`);

  const saveExpense = async (payload, id) => {
    if (id) await api.update(id, payload);
    else await api.create(payload);
    await refresh();
    setForm(null);
    setToast({ msg: id ? 'Changes saved' : `${payload.name} added` });
  };

  const saveTargets = async ({ upserts, deletes }) => {
    for (const [cat, n] of upserts) await api.setTarget(cat, n);
    for (const cat of deletes) await api.removeTarget(cat);
    await refresh();
    setShowTargets(false);
    setToast({ msg: 'Targets updated' });
  };

  const onBudgetChange = (n) => {
    setTotalBudget(n);
    budgetDirty.current = true;
    clearTimeout(budgetTimer.current);
    budgetTimer.current = setTimeout(async () => {
      try { await api.setTotalBudget(n); }
      catch (e) { setToast({ msg: e.message, error: true }); }
      finally { budgetDirty.current = false; }
    }, 500);
  };

  const headerDate = parseISO(todayISO).toLocaleDateString('en-IN', {
    weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
  });

  return (
    <div className="mx-auto max-w-6xl px-4 pb-24 pt-5 sm:px-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-emerald-600 text-white" aria-hidden="true">
            <CheckCheck className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-lg font-bold leading-tight">Bill Tracker</h1>
            <p className="text-xs text-stone-500 dark:text-stone-400">{headerDate}</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <div className="flex items-center rounded-lg border border-stone-300 dark:border-neutral-700" role="group" aria-label="Month">
            <button className="btn-ghost rounded-r-none p-2" onClick={() => setMonth((m) => shiftMonth(m, -1))} aria-label="Previous month">
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="min-w-[8.5rem] px-1 text-center text-sm font-medium" aria-live="polite">{label}</span>
            <button className="btn-ghost rounded-l-none p-2" onClick={() => setMonth((m) => shiftMonth(m, 1))} aria-label="Next month">
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
          {!isCurrentMonth && (
            <button className="btn-outline" onClick={() => setMonth(currentMonth)}>This month</button>
          )}
          <button className="btn-primary" onClick={() => setForm({})}>
            <Plus className="h-4 w-4" /> <span className="hidden sm:inline">Add expense</span><span className="sm:hidden">Add</span>
          </button>
          <button
            className="btn-outline p-2"
            onClick={toggleTheme}
            aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'}
            aria-pressed={dark}
            title={dark ? 'Light mode' : 'Dark mode'}
          >
            {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>
        </div>
      </header>

      {error && (
        <div role="alert" className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-200">
          <span>{error}</span>
          <button className="btn-outline" onClick={refresh}>Retry</button>
        </div>
      )}

      <div className="mt-5">
        <AlertBanner overdue={overdue} dueSoon={dueSoon} todayISO={todayISO} />
      </div>

      {!loaded ? (
        <p className="mt-16 text-center text-sm text-stone-500" role="status">Loading…</p>
      ) : (
        // On phones the wrappers dissolve (display: contents) so `order-*` interleaves the cards:
        // summary → timeline → variance → ledger. From lg up they become two real columns.
        <main className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_380px] lg:items-start">
          <div className="contents lg:flex lg:flex-col lg:gap-5">
            <UpcomingTimeline
              className="order-2"
              items={data.upcoming}
              days={days}
              onDaysChange={setDays}
              todayISO={todayISO}
              onPay={pay}
              onEdit={(expense) => setForm({ expense })}
              onAdd={() => setForm({})}
            />
            <ExpenseList
              className="order-4"
              expenses={data.expenses}
              monthLabel={label}
              onPay={pay}
              onUnpay={unpay}
              onEdit={(expense) => setForm({ expense })}
              onDelete={remove}
            />
          </div>
          <div className="contents lg:flex lg:flex-col lg:gap-5">
            <SummaryWidget
              className="order-1"
              summary={summary}
              monthLabel={label}
              perDay={perDay}
              daysLeft={daysLeft}
              onBudgetChange={onBudgetChange}
            />
            <VarianceModule
              className="order-3"
              variance={variance}
              monthLabel={label}
              onEditTargets={() => setShowTargets(true)}
            />
          </div>
        </main>
      )}

      {form && (
        <ExpenseForm
          expense={form.expense}
          categories={data.categories}
          todayISO={todayISO}
          onSubmit={saveExpense}
          onClose={() => setForm(null)}
        />
      )}
      {showTargets && (
        <BudgetsModal
          budgets={data.budgets}
          categories={data.categories}
          onSave={saveTargets}
          onClose={() => setShowTargets(false)}
        />
      )}
      <Toast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}
