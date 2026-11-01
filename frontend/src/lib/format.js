const inr0 = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 });
const inr2 = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** ₹1,23,456 - paise only when there are some. */
export function money(n) {
  const v = Math.round((Number(n) || 0) * 100) / 100;
  return (Number.isInteger(v) ? inr0 : inr2).format(v);
}

/** +₹1,200 (under target) / −₹800 (over target) / ₹0 */
export function signedMoney(n) {
  const v = Math.round((Number(n) || 0) * 100) / 100;
  if (v > 0) return `+${money(v)}`;
  if (v < 0) return `−${money(-v)}`;
  return money(0);
}

const pad = (n) => String(n).padStart(2, '0');

/** Local calendar date as YYYY-MM-DD (not UTC - important just after midnight in India). */
export function localISO(d = new Date()) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function parseISO(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d);
}

export function shiftMonth(key, delta) {
  const [y, m] = key.split('-').map(Number);
  const d = new Date(y, m - 1 + delta, 1);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}`;
}

export function monthLabel(key) {
  return parseISO(`${key}-01`).toLocaleDateString('en-IN', { month: 'long', year: 'numeric' });
}

export function daysInMonth(key) {
  const [y, m] = key.split('-').map(Number);
  return new Date(y, m, 0).getDate();
}

/** "Today", "Tomorrow", "Wed, 4 Nov" (adds the year when it is not the current one). */
export function dayLabel(iso, todayISO) {
  const diff = Math.round((parseISO(iso) - parseISO(todayISO)) / 86400000);
  if (diff === 0) return 'Today';
  if (diff === 1) return 'Tomorrow';
  if (diff === -1) return 'Yesterday';
  const d = parseISO(iso);
  const sameYear = d.getFullYear() === parseISO(todayISO).getFullYear();
  return d.toLocaleDateString('en-IN', {
    weekday: 'short', day: 'numeric', month: 'short', ...(sameYear ? {} : { year: 'numeric' }),
  });
}

export function shortDate(iso) {
  return parseISO(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
}
