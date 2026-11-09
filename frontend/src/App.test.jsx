import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import { localISO, parseISO } from './lib/format';

// ---- a tiny in-memory stand-in for the FastAPI backend ---------------------------------
let store;
let calls;

function decorate(e) {
  const today = parseISO(localISO());
  const days_left = Math.round((parseISO(e.due_date) - today) / 86400000);
  const urgency = e.paid ? 'paid' : days_left < 0 ? 'overdue' : days_left <= 1 ? 'urgent' : days_left <= 3 ? 'soon' : 'later';
  return { recurring: 'none', paid_on: null, generated_from: null, ...e, days_left, urgency };
}

function fakeFetch(url, init = {}) {
  const u = new URL(url, 'http://test');
  const method = init.method ?? 'GET';
  const body = init.body ? JSON.parse(init.body) : undefined;
  calls.push({ method, path: u.pathname, body });
  const ok = (data, status = 200) =>
    Promise.resolve({ ok: true, status, statusText: 'OK', json: async () => structuredClone(data) });

  const fail = (status, detail) =>
    Promise.resolve({ ok: false, status, statusText: 'Error', json: async () => ({ detail }) });

  const p = u.pathname;
  if (p === '/api/auth/me') return store.user ? ok(store.user) : fail(401, 'Please log in');
  if (p === '/api/auth/login') {
    if (body.email !== 'me@example.com' || body.password !== 'correct horse') return fail(401, 'Wrong email or password');
    store.user = { id: 1, email: body.email };
    return ok(store.user);
  }
  if (p === '/api/auth/register') { store.user = { id: 2, email: body.email }; return ok(store.user, 201); }
  if (p === '/api/auth/logout') { store.user = null; return ok(null, 204); }
  if (!store.user) return fail(401, 'Please log in');
  if (p === '/api/expenses' && method === 'GET') {
    const month = u.searchParams.get('month');
    return ok([...store.expenses, ...store.projected].filter((e) => e.due_date.startsWith(month)).map(decorate));
  }
  if (p === '/api/upcoming') {
    return ok([...store.expenses.filter((e) => !e.paid && e.payment_mode !== 'credit_card'), ...store.projected, ...store.cardBills]
      .map(decorate));
  }
  if (p === '/api/budgets') return ok(store.budgets);
  if (p === '/api/loans' && method === 'GET') return ok(store.loans);
  if (p === '/api/loans' && method === 'POST') {
    const l = { id: 50 + store.loans.length, repaid: 0, outstanding: body.amount, status: 'open', repayments: [],
      reminder_due: false, next_remind_on: body.first_reminder_on, days_to_due: null, overdue: false, ...body };
    store.loans.push(l);
    return ok(l, 201);
  }
  const repayM = p.match(/^\/api\/loans\/(\d+)\/repayments$/);
  if (repayM) {
    const l = store.loans.find((x) => x.id === Number(repayM[1]));
    l.repayments = [...l.repayments, { id: 900 + l.repayments.length, amount: body.amount, paid_on: body.paid_on }];
    l.repaid += body.amount;
    l.outstanding -= body.amount;
    if (l.outstanding <= 0) { l.status = 'repaid'; l.reminder_due = false; }
    return ok(l, 201);
  }
  const remindM = p.match(/^\/api\/loans\/(\d+)\/reminded$/);
  if (remindM) {
    const l = store.loans.find((x) => x.id === Number(remindM[1]));
    l.reminder_due = false;
    l.next_remind_on = '2026-11-17';
    return ok(l);
  }
  if (p === '/api/cards' && method === 'GET') return ok(store.cards);
  const payCardM = p.match(/^\/api\/cards\/(\d+)\/pay$/);
  if (payCardM) {
    const c = store.cards.find((x) => x.id === Number(payCardM[1]));
    c.unpaid_statements = c.unpaid_statements.filter((st) => st.statement_date !== body.statement_date);
    c.due_now = 0;
    store.cardBills = store.cardBills.filter((b) => b.statement_date !== body.statement_date);
    return ok(c);
  }
  if (p === '/api/settings' && method === 'GET') return ok({ total_budget: store.total });
  if (p === '/api/settings' && method === 'PUT') { store.total = body.total_budget; return ok({ total_budget: store.total }); }
  if (p === '/api/categories') return ok([...new Set(store.expenses.map((e) => e.category))].sort());
  if (p === '/api/expenses' && method === 'POST') {
    const e = { id: 100 + store.expenses.length, paid: false, ...body };
    store.expenses.push(e);
    return ok(decorate(e), 201);
  }
  const pay = p.match(/^\/api\/expenses\/(\d+)\/pay$/);
  if (pay) {
    const e = store.expenses.find((x) => x.id === Number(pay[1]));
    e.paid = true;
    return ok(decorate(e));
  }
  const one = p.match(/^\/api\/expenses\/(\d+)$/);
  if (one && method === 'GET') return ok(decorate(store.expenses.find((x) => x.id === Number(one[1]))));
  if (one && method === 'PUT') {
    const e = store.expenses.find((x) => x.id === Number(one[1]));
    Object.assign(e, body);
    return ok(decorate(e));
  }
  throw new Error(`unhandled ${method} ${p}`);
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date(2026, 10, 10, 10, 0, 0)); // Tue 10 Nov 2026, local
  localStorage.clear();
  document.documentElement.classList.remove('dark');
  calls = [];
  store = {
    user: { id: 1, email: 'me@example.com' },
    total: 50000,
    budgets: [
      { category: 'Food', monthly_target: 1000 },
      { category: 'Subscriptions', monthly_target: 2500 },
    ],
    expenses: [
      { id: 1, name: 'Mobile Recharge', amount: 349, due_date: '2026-11-08', category: 'Utilities', paid: false },
      { id: 2, name: 'Rent', amount: 22000, due_date: '2026-11-10', category: 'Rent', paid: false, recurring: 'monthly' },
      { id: 3, name: 'Claude Pro', amount: 1950, due_date: '2026-11-12', category: 'Subscriptions', paid: false, recurring: 'monthly' },
      { id: 4, name: 'HDFC Credit Card', amount: 14200, due_date: '2026-11-20', category: 'Credit Cards', paid: false },
      { id: 5, name: 'Groceries', amount: 1240, due_date: '2026-11-03', category: 'Food', paid: true, paid_on: '2026-11-03' },
    ],
    projected: [],
    loans: [],
    cards: [],
    cardBills: [],
  };
  globalThis.fetch = vi.fn(async (url, init) => fakeFetch(url, init));
});

afterEach(() => vi.useRealTimers());

const timeline = () => screen.getByRole('region', { name: 'Upcoming bills' });
const rowsOf = (el) =>
  [...el.querySelectorAll('li[data-urgency]')].map((li) => [li.querySelector('.truncate').textContent, li.dataset.urgency]);

async function renderApp() {
  render(<App />);
  await screen.findByRole('region', { name: 'Upcoming bills' });
}

it('lists upcoming bills chronologically and colour-codes the next 3 days', async () => {
  await renderApp();
  expect(rowsOf(timeline())).toEqual([
    ['Mobile Recharge', 'overdue'],
    ['Rent', 'urgent'],
    ['Claude Pro', 'soon'],
    ['HDFC Credit Card', 'later'],
  ]);
});

it('shows a pre-notification banner for overdue and due-within-3-days bills', async () => {
  await renderApp();
  const banner = screen.getByRole('alert');
  expect(banner).toHaveTextContent('3 bills need attention');
  expect(banner).toHaveTextContent('1 overdue');
  expect(banner).toHaveTextContent('Claude Pro');
  expect(banner).not.toHaveTextContent('HDFC');
  expect(document.title).toBe('(3) Bill Tracker');
});

it('computes the remaining budget and spend variance', async () => {
  await renderApp();
  // 50,000 - (349 + 22,000 + 1,950 + 14,200 + 1,240) = 10,261
  expect(screen.getByTestId('remaining')).toHaveTextContent('₹10,261');
  // targets 3,500 vs actual 39,739
  expect(screen.getByTestId('total-variance')).toHaveTextContent('−₹36,239');
  const food = document.querySelector('li[data-status="over"]');
  expect(food).toHaveTextContent('Food');
  expect(food).toHaveTextContent('−₹240');
  expect(document.querySelector('li[data-status="under"]')).toHaveTextContent('+₹550');
});

it('updates the remaining budget live while the budget is edited', async () => {
  const user = userEvent.setup({ advanceTimers: () => {} });
  await renderApp();
  const input = screen.getByLabelText('Monthly budget');
  await user.clear(input);
  await user.type(input, '60000');
  expect(screen.getByTestId('remaining')).toHaveTextContent('₹20,261');
  await user.clear(input);
  await user.type(input, '30000');
  expect(screen.getByTestId('remaining')).toHaveTextContent('−₹9,739');
});

it('marking a bill paid refreshes the alerts and totals', async () => {
  const user = userEvent.setup();
  await renderApp();
  await user.click(within(timeline()).getByRole('button', { name: 'Mark Mobile Recharge as paid' }));
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('2 bills need attention'));
  expect(calls.some((c) => c.method === 'POST' && c.path === '/api/expenses/1/pay')).toBe(true);
  expect(rowsOf(timeline()).map((r) => r[0])).not.toContain('Mobile Recharge');
});

it('shows projected recurring bills without pay/edit/delete and counts them in next month', async () => {
  const user = userEvent.setup();
  store.projected = [{
    id: null, projected: true, projected_from: 2, name: 'Rent', amount: 22000,
    due_date: '2026-12-10', category: 'Rent', paid: false, recurring: 'monthly',
  }];
  await renderApp();
  const row = timeline().querySelector('li[data-projected]');
  expect(row).toHaveTextContent('Rent');
  expect(row).toHaveTextContent('Projected');
  expect(within(row).queryByRole('button')).toBeNull();

  await user.click(screen.getByRole('button', { name: 'Next month' }));
  const ledger = screen.getByRole('region', { name: 'All expenses' });
  await waitFor(() => expect(ledger.querySelector('li[data-projected]')).toHaveTextContent('Rent'));
  expect(within(ledger).queryByRole('button', { name: 'Delete Rent' })).toBeNull();
  // 50,000 - 22,000 projected rent
  expect(screen.getByTestId('remaining')).toHaveTextContent('₹28,000');
  expect(screen.getByText(/incl\. ₹22,000 of projected recurring bills/)).toBeInTheDocument();
});

it('toggles dark mode and remembers it', async () => {
  const user = userEvent.setup();
  await renderApp();
  await user.click(screen.getByRole('button', { name: 'Switch to dark mode' }));
  expect(document.documentElement).toHaveClass('dark');
  expect(localStorage.getItem('ft-theme')).toBe('dark');
  await user.click(screen.getByRole('button', { name: 'Switch to light mode' }));
  expect(document.documentElement).not.toHaveClass('dark');
});

it('validates and submits the add-expense form', async () => {
  const user = userEvent.setup();
  await renderApp();
  await user.click(screen.getByRole('button', { name: /add expense/i }));
  const dialog = await screen.findByRole('dialog', { name: 'Add expense' });

  await user.click(within(dialog).getByRole('button', { name: 'Add expense' }));
  expect(within(dialog).getByText('Give this expense a name')).toBeInTheDocument();
  expect(within(dialog).getByText('Enter an amount greater than 0')).toBeInTheDocument();
  expect(within(dialog).getByText('Choose or type a category')).toBeInTheDocument();

  await user.type(within(dialog).getByLabelText('Expense name'), 'EatClub');
  await user.type(within(dialog).getByLabelText('Amount (₹)'), '149');
  await user.type(within(dialog).getByLabelText('Category'), 'Subscriptions');
  await user.click(within(dialog).getByRole('button', { name: 'Add expense' }));

  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  const post = calls.find((c) => c.method === 'POST' && c.path === '/api/expenses');
  expect(post.body).toEqual({
    name: 'EatClub', amount: 149, due_date: '2026-11-10', category: 'Subscriptions', recurring: 'monthly',
    payment_mode: null, card_id: null,
  });
  // 50,000 - 39,739 - 149
  await waitFor(() => expect(screen.getByTestId('remaining')).toHaveTextContent('₹10,112'));
});

it('asks for a login, then shows only after signing in', async () => {
  const user = userEvent.setup();
  store.user = null;
  render(<App />);
  const submit = async () => (await screen.findAllByRole('button', { name: 'Log in' })).at(-1);
  await user.click(await submit());
  expect(screen.getByText('Enter a valid email address')).toBeInTheDocument();
  expect(screen.queryByText('Rent')).not.toBeInTheDocument();

  await user.type(screen.getByLabelText('Email'), 'me@example.com');
  await user.type(screen.getByLabelText('Password'), 'not it');
  await user.click(await submit());
  expect(await screen.findByRole('alert')).toHaveTextContent('Wrong email or password');

  await user.clear(screen.getByLabelText('Password'));
  await user.type(screen.getByLabelText('Password'), 'correct horse');
  await user.click(await submit());
  await screen.findByRole('region', { name: 'Upcoming bills' });
  expect(rowsOf(timeline()).map((r) => r[0])).toContain('Rent');
});

it('creating an account checks the password length first', async () => {
  const user = userEvent.setup();
  store.user = null;
  render(<App />);
  await user.click(await screen.findByRole('button', { name: 'Create account' }));
  await user.type(screen.getByLabelText('Email'), 'new@example.com');
  await user.type(screen.getByLabelText('Password'), 'short');
  await user.click(screen.getAllByRole('button', { name: 'Create account' }).at(-1));
  expect(screen.getByText('Use at least 8 characters')).toBeInTheDocument();
  expect(calls.some((c) => c.path === '/api/auth/register')).toBe(false);

  await user.type(screen.getByLabelText('Password'), '-and-longer');
  await user.click(screen.getAllByRole('button', { name: 'Create account' }).at(-1));
  await screen.findByRole('region', { name: 'Upcoming bills' });
  expect(calls.find((c) => c.path === '/api/auth/register').body).toEqual({
    email: 'new@example.com', password: 'short-and-longer' });
});

it('logging out returns to the login screen and hides the data', async () => {
  const user = userEvent.setup();
  await renderApp();
  await user.click(screen.getByRole('button', { name: 'Log out me@example.com' }));
  expect(await screen.findByLabelText('Password')).toBeInTheDocument();
  expect(screen.queryByRole('region', { name: 'Upcoming bills' })).not.toBeInTheDocument();
  expect(store.user).toBeNull();
});

it('an expired session sends you back to log in', async () => {
  const user = userEvent.setup();
  await renderApp();
  store.user = null; // the server forgot the session
  await user.click(within(timeline()).getByRole('button', { name: 'Mark Mobile Recharge as paid' }));
  expect(await screen.findByLabelText('Password')).toBeInTheDocument();
});

it('money paid back is shown on the bill and not counted against the budget', async () => {
  store.expenses[3] = { ...store.expenses[3], reimbursed: 4000, reimbursed_note: 'Rahul' }; // HDFC card 14,200
  await renderApp();
  // 50,000 - (39,739 - 4,000)
  expect(screen.getByTestId('remaining')).toHaveTextContent('₹14,261');
  expect(screen.getByTestId('paid-back')).toHaveTextContent('−₹4,000');
  expect(screen.getByTestId('paid-back-tag')).toHaveTextContent('−₹4,000 paid back · Rahul');
  // the timeline still shows the full card bill as due
  const row = [...timeline().querySelectorAll('li[data-urgency]')].find((li) => li.textContent.includes('HDFC'));
  expect(row).toHaveTextContent('₹14,200');
});

it('records a paid-back amount from the form and checks it fits the bill', async () => {
  const user = userEvent.setup();
  await renderApp();
  await user.click(screen.getByRole('button', { name: /add expense/i }));
  const dialog = await screen.findByRole('dialog', { name: 'Add expense' });
  await user.type(within(dialog).getByLabelText('Expense name'), 'ICICI Card');
  await user.type(within(dialog).getByLabelText('Amount (₹)'), '5000');
  await user.type(within(dialog).getByLabelText('Category'), 'Credit Cards');
  await user.click(within(dialog).getByRole('button', { name: '+ Someone paid me back part of this' }));
  await user.type(within(dialog).getByLabelText('Amount paid back (₹)'), '6000');
  await user.click(within(dialog).getByRole('button', { name: 'Add expense' }));
  expect(within(dialog).getByText('Cannot be more than the amount')).toBeInTheDocument();

  await user.clear(within(dialog).getByLabelText('Amount paid back (₹)'));
  await user.type(within(dialog).getByLabelText('Amount paid back (₹)'), '1500');
  await user.type(within(dialog).getByLabelText('From / for (optional)'), 'Asha - dinner');
  expect(within(dialog).getByText(/Counts as ₹3,500 of your own spending/)).toBeInTheDocument();
  await user.click(within(dialog).getByRole('button', { name: 'Add expense' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(calls.find((c) => c.method === 'POST' && c.path === '/api/expenses').body).toMatchObject({
    name: 'ICICI Card', amount: 5000, reimbursed: 1500, reimbursed_note: 'Asha - dinner',
  });
});

it('a brand-new account still gets category suggestions it can click', async () => {
  const user = userEvent.setup();
  store.expenses = [];
  store.budgets = [];
  await renderApp();
  await user.click(screen.getByRole('button', { name: /add expense/i }));
  const dialog = await screen.findByRole('dialog', { name: 'Add expense' });
  const chips = within(dialog).getByRole('group', { name: 'Suggested categories' });
  expect(within(chips).getAllByRole('button').map((b) => b.textContent)).toContain('Utilities');
  await user.click(within(chips).getByRole('button', { name: 'Utilities' }));
  expect(within(dialog).getByLabelText('Category')).toHaveValue('Utilities');
  expect(within(chips).getByRole('button', { name: 'Utilities' })).toHaveAttribute('aria-pressed', 'true');
});

// ---- lending -------------------------------------------------------------------------
const loan = (over) => ({
  id: 7, person: 'Rahul', amount: 5000, lent_on: '2026-10-20', due_date: '2026-11-05', note: null, repaid: 2000,
  outstanding: 3000, status: 'open', days_to_due: -5, overdue: true, remind_every_days: 7,
  next_remind_on: '2026-11-10', reminder_due: true, repayments: [{ id: 1, amount: 2000, paid_on: '2026-10-28' }], ...over,
});
const loansPanel = () => screen.getByRole('region', { name: 'Money lent' });

it('reminds you to ask for money back until you say you asked', async () => {
  const user = userEvent.setup();
  store.loans = [loan()];
  await renderApp();
  expect(screen.getByTestId('loan-reminders')).toHaveTextContent('Ask Rahul for ₹3,000 back');
  expect(document.title).toBe('(4) Bill Tracker');
  expect(loansPanel()).toHaveTextContent('₹3,000 owed to you by 1 person');
  expect(loansPanel()).toHaveTextContent('₹3,000 left of ₹5,000');
  expect(loansPanel()).toHaveTextContent('5d past due');
  await user.click(within(loansPanel()).getByRole('button', { name: "I've asked" }));
  await waitFor(() => expect(screen.queryByTestId('loan-reminders')).not.toBeInTheDocument());
  expect(calls.some((c) => c.method === 'POST' && c.path === '/api/loans/7/reminded')).toBe(true);
  expect(loansPanel()).toHaveTextContent('Next reminder 17 Nov · every week');
});

it('lends money with a reminder schedule', async () => {
  const user = userEvent.setup();
  await renderApp();
  await user.click(within(loansPanel()).getByRole('button', { name: 'Lend' }));
  const dialog = await screen.findByRole('dialog', { name: 'Lend money' });
  await user.click(within(dialog).getByRole('button', { name: 'Save loan' }));
  expect(within(dialog).getByText('Who did you lend it to?')).toBeInTheDocument();
  await user.type(within(dialog).getByLabelText('Lent to'), 'Asha');
  await user.type(within(dialog).getByLabelText('Amount (₹)'), '2,500');
  await user.type(within(dialog).getByLabelText('Get it back by (optional)'), '2026-11-30');
  await user.selectOptions(within(dialog).getByLabelText('Remind me to ask'), '3');
  expect(within(dialog).getByText(/Starts the day it's due back \(30 Nov\), then every 3 days/)).toBeInTheDocument();
  await user.click(within(dialog).getByRole('button', { name: 'Save loan' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(calls.find((c) => c.method === 'POST' && c.path === '/api/loans').body).toEqual({
    person: 'Asha', amount: 2500, lent_on: '2026-11-10', due_date: '2026-11-30', note: null,
    remind_every_days: 3, first_reminder_on: null,
  });
  expect(loansPanel()).toHaveTextContent('Asha');
});

it('records money paid back and closes the loan', async () => {
  const user = userEvent.setup();
  store.loans = [loan({ reminder_due: false })];
  await renderApp();
  await user.click(within(loansPanel()).getByRole('button', { name: 'Got money back' }));
  const dialog = await screen.findByRole('dialog', { name: 'Money back from Rahul' });
  expect(within(dialog).getByLabelText('Amount received (₹)')).toHaveValue('3000');
  await user.click(within(dialog).getByRole('button', { name: 'Record repayment' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(calls.find((c) => c.path === '/api/loans/7/repayments').body).toEqual({ amount: 3000, paid_on: '2026-11-10' });
  expect(await screen.findByText('Rahul has paid you back in full')).toBeInTheDocument();
  expect(loansPanel()).toHaveTextContent('Nobody owes you money');
});

// ---- credit cards ------------------------------------------------------------------------
const hdfc = () => ({
  id: 1, name: 'HDFC', kind: 'credit', statement_day: 15, due_day: 5, due_now: 4200, charged_this_cycle: 800, emi_remaining: 4000,
  total_owed: 9000,
  unpaid_statements: [{ statement_date: '2026-10-15', due_date: '2026-11-05', total: 4200, paid: 0, balance: 4200, overdue: true,
    items: [{ date: '2026-10-10', name: 'Groceries', amount: 1200, expense_id: 40 },
      { date: '2026-10-14', name: 'Shoes', amount: 3000, expense_id: 41 }] }],
  current_statement: { statement_date: '2026-11-15', due_date: '2026-12-05', total: 2800, paid: 0, balance: 2800, overdue: false,
    items: [{ date: '2026-10-25', name: 'Dinner', amount: 800 }, { date: '2026-11-20', name: 'iPhone EMI 2/3', amount: 2000 }] },
  emis: [{ id: 3, card_id: 1, name: 'iPhone', category: 'Electronics', monthly_amount: 2000, first_date: '2026-10-20',
    last_date: '2026-12-20', months: 3, months_done: 1, months_left: 2, remaining: 4000 }],
});
const cardsPanel = () => screen.getByRole('region', { name: 'Cards' });

it('shows what you owe each card and pays the bill from the timeline', async () => {
  const user = userEvent.setup();
  store.cards = [hdfc()];
  store.cardBills = [{ id: null, kind: 'card_bill', name: 'HDFC bill', amount: 4200, due_date: '2026-11-05',
    category: 'Credit card bill', paid: false, projected: false, card_id: 1, statement_date: '2026-10-15' }];
  await renderApp();
  expect(within(cardsPanel()).getByTestId('card-total')).toHaveTextContent('₹9,000');
  expect(cardsPanel()).toHaveTextContent('EMIs still to come₹4,000');
  expect(cardsPanel()).toHaveTextContent('1 of 3 paid · ends Dec 2026');
  // each bill lists the purchases on it
  expect(within(cardsPanel()).getAllByText('2 items on this bill', { selector: 'summary' })).toHaveLength(2);
  expect(cardsPanel()).toHaveTextContent('14 Oct · Shoes₹3,000');
  expect(cardsPanel()).toHaveTextContent('20 Nov · iPhone EMI 2/3 · upcoming₹2,000');
  const row = [...timeline().querySelectorAll('li[data-urgency]')].find((li) => li.textContent.includes('HDFC bill'));
  expect(row).toHaveTextContent('Statement 15 Oct');
  expect(within(row).queryByRole('button', { name: 'Edit HDFC bill' })).toBeNull();
  await user.click(within(row).getByRole('button', { name: 'Mark HDFC bill as paid' }));
  await waitFor(() => expect(rowsOf(timeline()).map((r) => r[0])).not.toContain('HDFC bill'));
  expect(calls.find((c) => c.path === '/api/cards/1/pay').body).toEqual({ statement_date: '2026-10-15' });
});

it('a purchase on a card bill can be edited from the bill, even from another month', async () => {
  const user = userEvent.setup();
  const icici = { ...hdfc(), id: 2, name: 'ICICI', unpaid_statements: [], current_statement: null, emis: [] };
  store.cards = [hdfc(), icici];
  store.expenses.push({ id: 41, name: 'Shoes', amount: 3000, due_date: '2026-10-14', category: 'Shopping', paid: true,
    payment_mode: 'credit_card', card_id: 1 });
  await renderApp();
  const panel = cardsPanel();
  await user.click(within(panel).getAllByText('2 items on this bill', { selector: 'summary' })[0]);
  // EMI instalments are edited from the EMI list, so only purchases get a button here
  expect(within(panel).queryByRole('button', { name: 'Edit iPhone EMI 2/3' })).toBeNull();
  await user.click(within(panel).getByRole('button', { name: 'Edit Shoes' }));
  const dialog = await screen.findByRole('dialog', { name: 'Edit expense' });
  expect(within(dialog).getByLabelText('Expense name')).toHaveValue('Shoes');
  await user.selectOptions(within(dialog).getByLabelText('Card'), '2');
  await user.click(within(dialog).getByRole('button', { name: 'Save changes' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(calls.find((c) => c.method === 'PUT' && c.path === '/api/expenses/41').body).toMatchObject({
    name: 'Shoes', payment_mode: 'credit_card', card_id: 2 });
});

it('a purchase can be paid by credit card', async () => {
  const user = userEvent.setup();
  store.cards = [hdfc()];
  await renderApp();
  await user.click(screen.getByRole('button', { name: /add expense/i }));
  const dialog = await screen.findByRole('dialog', { name: 'Add expense' });
  await user.type(within(dialog).getByLabelText('Expense name'), 'Shoes');
  await user.type(within(dialog).getByLabelText('Amount (₹)'), '3000');
  await user.type(within(dialog).getByLabelText('Category'), 'Shopping');
  await user.selectOptions(within(dialog).getByLabelText('Paid with'), 'credit_card');
  expect(within(dialog).getByLabelText('Card')).toHaveValue('1');
  expect(within(dialog).getByText(/goes on that card's bill/)).toBeInTheDocument();
  await user.click(within(dialog).getByRole('radio', { name: 'One-time' }));
  await user.click(within(dialog).getByRole('button', { name: 'Add expense' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(calls.find((c) => c.method === 'POST' && c.path === '/api/expenses').body).toMatchObject({
    name: 'Shoes', amount: 3000, payment_mode: 'credit_card', card_id: 1, recurring: 'none',
  });
});

it('debit cards are listed and can be picked as the card a payment came from', async () => {
  const user = userEvent.setup();
  const sbi = { id: 2, name: 'SBI Savings', kind: 'debit', statement_day: null, due_day: null, due_now: 0,
    unpaid_statements: [], current_statement: null, charged_this_cycle: 0, emi_remaining: 0, total_owed: 0, emis: [] };
  store.cards = [hdfc(), sbi];
  await renderApp();
  expect(within(cardsPanel()).getByText('Debit cards')).toBeInTheDocument();
  expect(cardsPanel().querySelector('[data-card="SBI Savings"]')).not.toBeNull();
  await user.click(screen.getByRole('button', { name: /add expense/i }));
  const dialog = await screen.findByRole('dialog', { name: 'Add expense' });
  await user.type(within(dialog).getByLabelText('Expense name'), 'Fuel');
  await user.type(within(dialog).getByLabelText('Amount (₹)'), '2000');
  await user.type(within(dialog).getByLabelText('Category'), 'Transport');
  await user.selectOptions(within(dialog).getByLabelText('Paid with'), 'debit_card');
  const card = within(dialog).getByLabelText('Card');
  expect([...card.options].map((o) => o.textContent)).toEqual(['Not saying', 'SBI Savings']); // only debit cards
  await user.selectOptions(card, '2');
  await user.click(within(dialog).getByRole('button', { name: 'Add expense' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(calls.find((c) => c.method === 'POST' && c.path === '/api/expenses').body)
    .toMatchObject({ payment_mode: 'debit_card', card_id: 2 });
});

it('EMI instalments appear as read-only spending rows', async () => {
  store.cards = [hdfc()];
  store.expenses.push({ id: null, kind: 'emi', emi_id: 3, name: 'iPhone EMI 2/3', amount: 2000, due_date: '2026-11-20',
    category: 'Electronics', paid: false, recurring: 'monthly', payment_mode: 'credit_card', card_id: 1 });
  await renderApp();
  const ledger = screen.getByRole('region', { name: 'All expenses' });
  const row = ledger.querySelector('li[data-kind="emi"]');
  expect(row).toHaveTextContent('iPhone EMI 2/3');
  expect(row).toHaveTextContent('EMI');
  expect(row).toHaveTextContent('HDFC card');
  expect(within(row).queryByRole('button')).toBeNull();
  // counts as spending: 50,000 - (39,739 + 2,000)
  expect(screen.getByTestId('remaining')).toHaveTextContent('₹8,261');
});

it('shows a helpful message when the API is down', async () => {
  globalThis.fetch = vi.fn(async () => { throw new TypeError('network'); });
  render(<App />);
  expect(await screen.findByText(/Cannot reach the API/)).toBeInTheDocument();
});
