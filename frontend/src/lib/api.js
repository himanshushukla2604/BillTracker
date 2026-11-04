import { localISO } from './format';

async function req(method, path, { params = {}, body } = {}) {
  // Always send the browser's local date so "due today" is right in any time zone.
  const qs = new URLSearchParams({ today: localISO() });
  for (const [k, v] of Object.entries(params)) if (v != null) qs.set(k, v);
  let res;
  try {
    res = await fetch(`/api${path}?${qs}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new Error(`Cannot reach the API. Is the backend running on port ${__API_PORT__}?`);
  }
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const j = await res.json();
      if (typeof j.detail === 'string') msg = j.detail;
      else if (Array.isArray(j.detail)) {
        msg = j.detail.map((d) => `${d.loc?.slice(-1)[0] ?? 'field'}: ${d.msg}`).join('; ');
      }
    } catch { /* keep the status text */ }
    throw Object.assign(new Error(msg), { status: res.status });
  }
  return res.status === 204 ? null : res.json();
}

export const api = {
  me: () => req('GET', '/auth/me'),
  login: (email, password) => req('POST', '/auth/login', { body: { email, password } }),
  register: (email, password) => req('POST', '/auth/register', { body: { email, password } }),
  logout: () => req('POST', '/auth/logout'),
  expenses: (month) => req('GET', '/expenses', { params: { month } }),
  upcoming: (days) => req('GET', '/upcoming', { params: { days } }),
  budgets: () => req('GET', '/budgets'),
  settings: () => req('GET', '/settings'),
  categories: () => req('GET', '/categories'),
  create: (body) => req('POST', '/expenses', { body }),
  update: (id, body) => req('PUT', `/expenses/${id}`, { body }),
  remove: (id) => req('DELETE', `/expenses/${id}`),
  pay: (id) => req('POST', `/expenses/${id}/pay`),
  unpay: (id) => req('POST', `/expenses/${id}/unpay`),
  setTotalBudget: (total_budget) => req('PUT', '/settings', { body: { total_budget } }),
  setTarget: (category, monthly_target) =>
    req('PUT', `/budgets/${encodeURIComponent(category)}`, { body: { monthly_target } }),
  removeTarget: (category) => req('DELETE', `/budgets/${encodeURIComponent(category)}`),

  loans: () => req('GET', '/loans'),
  createLoan: (body) => req('POST', '/loans', { body }),
  updateLoan: (id, body) => req('PUT', `/loans/${id}`, { body }),
  removeLoan: (id) => req('DELETE', `/loans/${id}`),
  repay: (id, body) => req('POST', `/loans/${id}/repayments`, { body }),
  undoRepay: (id, repaymentId) => req('DELETE', `/loans/${id}/repayments/${repaymentId}`),
  reminded: (id) => req('POST', `/loans/${id}/reminded`),

  cards: () => req('GET', '/cards'),
  createCard: (body) => req('POST', '/cards', { body }),
  updateCard: (id, body) => req('PUT', `/cards/${id}`, { body }),
  removeCard: (id) => req('DELETE', `/cards/${id}`),
  payCard: (id, statement_date, amount) => req('POST', `/cards/${id}/pay`, { body: { statement_date, amount } }),
  unpayCard: (id, statement_date) => req('POST', `/cards/${id}/unpay`, { body: { statement_date } }),
  createEmi: (cardId, body) => req('POST', `/cards/${cardId}/emis`, { body }),
  updateEmi: (id, body) => req('PUT', `/emis/${id}`, { body }),
  removeEmi: (id) => req('DELETE', `/emis/${id}`),
};
