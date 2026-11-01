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
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}

export const api = {
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
};
