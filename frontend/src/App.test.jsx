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
    Promise.resolve({ ok: true, status, statusText: 'OK', json: async () => data });

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
  if (p === '/api/upcoming') return ok([...store.expenses.filter((e) => !e.paid), ...store.projected].map(decorate));
  if (p === '/api/budgets') return ok(store.budgets);
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

it('shows a helpful message when the API is down', async () => {
  globalThis.fetch = vi.fn(async () => { throw new TypeError('network'); });
  render(<App />);
  expect(await screen.findByText(/Cannot reach the API/)).toBeInTheDocument();
});
