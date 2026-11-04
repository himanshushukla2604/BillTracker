import { useEffect, useState } from 'react';
import { Bell, BellRing, TriangleAlert } from 'lucide-react';
import { money } from '../lib/format';
import { dueText, itemKey } from '../lib/urgency';

const billsTitle = (n) => `${n} bill${n > 1 ? 's' : ''} need${n > 1 ? '' : 's'} attention`;
const askText = (l) => `Ask ${l.person} for ${money(l.outstanding)} back`;

/** Bills overdue or due within 3 days, plus loans whose reminder to ask for the money back is due. */
export default function AlertBanner({ overdue, dueSoon, reminders = [], todayISO }) {
  const [perm, setPerm] = useState(() =>
    typeof Notification !== 'undefined' ? Notification.permission : 'unsupported',
  );
  const items = [...overdue, ...dueSoon];
  const count = items.length;
  const total = items.reduce((s, i) => s + i.amount, 0);

  // Once per day, if the person opted in, also raise a system notification.
  useEffect(() => {
    if (perm !== 'granted' || !(count || reminders.length)) return;
    try {
      if (localStorage.getItem('ft-notified') === todayISO) return;
      const lines = [
        ...items.slice(0, 4).map((i) => `${i.name} (${dueText(i).toLowerCase()})`),
        ...reminders.slice(0, 3).map(askText),
      ];
      new Notification(count ? billsTitle(count) : 'Time to ask for your money back', { body: lines.join(', ') });
      localStorage.setItem('ft-notified', todayISO);
    } catch { /* notifications unavailable */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [perm, count, reminders.length, todayISO]);

  if (!count && !reminders.length) return null;

  const severe = overdue.length > 0 || dueSoon.some((i) => i.urgency === 'urgent');
  const Icon = count ? TriangleAlert : BellRing;
  return (
    <div
      role="alert"
      className={`flex flex-wrap items-start gap-3 rounded-2xl border px-4 py-3 ${
        severe
          ? 'border-rose-200 bg-rose-50 text-rose-900 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-100'
          : 'border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100'
      }`}
    >
      <Icon className="mt-0.5 h-5 w-5 shrink-0" />
      <div className="min-w-0 flex-1">
        {count > 0 && (
          <>
            <p className="text-sm font-semibold">
              {billsTitle(count)} · <span className="num">{money(total)}</span>
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
          </>
        )}
        {reminders.length > 0 && (
          <p className={`text-sm ${count ? 'mt-1.5 opacity-90' : 'font-semibold'}`} data-testid="loan-reminders">
            {!count && 'Time to ask for your money back: '}
            {count > 0 && <BellRing className="mr-1 inline h-3.5 w-3.5" />}
            {reminders.slice(0, 3).map((l, idx) => (
              <span key={l.id} className="num">{idx > 0 && ' · '}{askText(l)}</span>
            ))}
            {reminders.length > 3 && ` · +${reminders.length - 3} more`}
          </p>
        )}
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
