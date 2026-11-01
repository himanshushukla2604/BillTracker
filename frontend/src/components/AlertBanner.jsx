import { useEffect, useState } from 'react';
import { Bell, TriangleAlert } from 'lucide-react';
import { money } from '../lib/format';
import { dueText, itemKey } from '../lib/urgency';

export default function AlertBanner({ overdue, dueSoon, todayISO }) {
  const [perm, setPerm] = useState(() =>
    typeof Notification !== 'undefined' ? Notification.permission : 'unsupported',
  );
  const items = [...overdue, ...dueSoon];
  const count = items.length;
  const total = items.reduce((s, i) => s + i.amount, 0);

  // Once per day, if the person opted in, also raise a system notification.
  useEffect(() => {
    if (perm !== 'granted' || !count) return;
    try {
      if (localStorage.getItem('ft-notified') === todayISO) return;
      new Notification(`${count} bill${count > 1 ? 's' : ''} need attention`, {
        body: items.slice(0, 4).map((i) => `${i.name} (${dueText(i).toLowerCase()})`).join(', '),
      });
      localStorage.setItem('ft-notified', todayISO);
    } catch { /* notifications unavailable */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [perm, count, todayISO]);

  if (!count) return null;

  const severe = overdue.length > 0 || dueSoon.some((i) => i.urgency === 'urgent');
  return (
    <div
      role="alert"
      className={`flex flex-wrap items-start gap-3 rounded-2xl border px-4 py-3 ${
        severe
          ? 'border-rose-200 bg-rose-50 text-rose-900 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-100'
          : 'border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100'
      }`}
    >
      <TriangleAlert className="mt-0.5 h-5 w-5 shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold">
          {count} bill{count > 1 ? 's' : ''} need attention · <span className="num">{money(total)}</span>
        </p>
        <p className="mt-0.5 text-sm opacity-90">
          {overdue.length > 0 && `${overdue.length} overdue. `}
          {items.slice(0, 4).map((i, idx) => (
            <span key={itemKey(i)}>
              {idx > 0 && ' · '}
              {i.name} <span className="opacity-75">({dueText(i).toLowerCase()})</span>
            </span>
          ))}
          {count > 4 && ` · +${count - 4} more`}
        </p>
      </div>
      {perm === 'default' && (
        <button
          className="btn-outline shrink-0 border-current/30 text-xs"
          onClick={async () => setPerm(await Notification.requestPermission())}
        >
          <Bell className="h-3.5 w-3.5" /> Enable alerts
        </button>
      )}
    </div>
  );
}
