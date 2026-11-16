import { useState } from 'react';
import { Download } from 'lucide-react';
import { api } from '../lib/api';
import Modal from './Modal';

/** Your account: change the password, download everything, or delete the account for good. */
export default function AccountModal({ user, onClose, onPasswordChanged, onDeleted }) {
  return (
    <Modal title="Your account" onClose={onClose}>
      <p className="text-sm text-stone-500 dark:text-stone-400">
        Signed in as <span className="font-medium text-stone-900 dark:text-stone-100">{user.email}</span>
      </p>

      <ChangePassword email={user.email} onDone={onPasswordChanged} />

      <section className="mt-6 border-t border-stone-200 pt-5 dark:border-neutral-800" aria-labelledby="acc-data-h">
        <h3 id="acc-data-h" className="text-sm font-semibold">Your data</h3>
        <p className="mt-1 text-sm text-stone-500 dark:text-stone-400">
          Everything in your account as one JSON file.
        </p>
        <a className="btn-outline mt-3" href="/api/export" download>
          <Download className="h-4 w-4" /> Download your data
        </a>
      </section>

      <DeleteAccount onDeleted={onDeleted} />
    </Modal>
  );
}

function ChangePassword({ email, onDone }) {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    const found = {};
    if (!current) found.current = 'Enter your current password';
    if (next.length < 8) found.next = 'Use at least 8 characters';
    else if (next === current) found.next = 'Choose a password different from the current one';
    setErrors(found);
    if (Object.keys(found).length) return;
    setSaving(true);
    setFormError('');
    try {
      await api.changePassword(current, next);
      setCurrent('');
      setNext('');
      onDone();
    } catch (err) {
      setFormError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const err = (k) => errors[k] && <p id={`acc-${k}-err`} className="mt-1 text-xs text-rose-600 dark:text-rose-400">{errors[k]}</p>;
  const aria = (k) => ({ 'aria-invalid': Boolean(errors[k]), 'aria-describedby': errors[k] ? `acc-${k}-err` : undefined });

  return (
    <form onSubmit={submit} noValidate className="mt-5 space-y-4" aria-labelledby="acc-pw-h">
      <h3 id="acc-pw-h" className="text-sm font-semibold">Change password</h3>
      {/* lets password managers attach the new password to the right account */}
      <input type="email" autoComplete="username" value={email} readOnly hidden />
      <div>
        <label className="label" htmlFor="acc-current">Current password</label>
        <input id="acc-current" type="password" className="input" value={current} maxLength={128}
          onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" {...aria('current')} />
        {err('current')}
      </div>
      <div>
        <label className="label" htmlFor="acc-next">New password</label>
        <input id="acc-next" type="password" className="input" value={next} maxLength={128}
          onChange={(e) => setNext(e.target.value)} autoComplete="new-password" {...aria('next')} />
        {err('next') || (
          <p className="mt-1 text-xs text-stone-500 dark:text-stone-400">
            At least 8 characters. Your other devices are logged out.
          </p>
        )}
      </div>
      {formError && (
        <p role="alert" className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-950/50 dark:text-rose-300">
          {formError}
        </p>
      )}
      <button type="submit" className="btn-primary" disabled={saving}>
        {saving ? 'Saving…' : 'Change password'}
      </button>
    </form>
  );
}

function DeleteAccount({ onDeleted }) {
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [deleting, setDeleting] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!password) { setError('Enter your password to confirm'); return; }
    setDeleting(true);
    setError('');
    try {
      await api.deleteAccount(password);
      onDeleted();
    } catch (err) {
      setError(err.message);
      setDeleting(false);
    }
  };

  return (
    <section className="mt-6 border-t border-stone-200 pt-5 dark:border-neutral-800" aria-labelledby="acc-del-h">
      <h3 id="acc-del-h" className="text-sm font-semibold">Delete account</h3>
      <p className="mt-1 text-sm text-stone-500 dark:text-stone-400">
        Erases your account and every expense, bill, card, loan and goal in it. This cannot be undone,
        so download your data first if you want a copy.
      </p>
      {!open ? (
        <button className="btn-outline mt-3 text-rose-600 dark:text-rose-400" onClick={() => setOpen(true)}>
          Delete my account…
        </button>
      ) : (
        <form onSubmit={submit} noValidate className="mt-3 space-y-3">
          <div>
            <label className="label" htmlFor="acc-del-pw">Your password, to confirm</label>
            <input id="acc-del-pw" type="password" className="input" value={password} maxLength={128} autoFocus
              onChange={(e) => setPassword(e.target.value)} autoComplete="current-password"
              aria-invalid={Boolean(error)} aria-describedby={error ? 'acc-del-err' : undefined} />
            {error && <p id="acc-del-err" role="alert" className="mt-1 text-xs text-rose-600 dark:text-rose-400">{error}</p>}
          </div>
          <div className="flex gap-2">
            <button type="button" className="btn-outline" onClick={() => { setOpen(false); setPassword(''); setError(''); }}>
              Keep my account
            </button>
            <button type="submit" className="btn bg-rose-600 text-white hover:bg-rose-700" disabled={deleting}>
              {deleting ? 'Deleting…' : 'Delete everything'}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
