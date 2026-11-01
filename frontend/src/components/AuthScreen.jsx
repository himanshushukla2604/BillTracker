import { useEffect, useRef, useState } from 'react';
import { CheckCheck } from 'lucide-react';
import { api } from '../lib/api';

const MODES = [
  ['login', 'Log in'],
  ['register', 'Create account'],
];

export default function AuthScreen({ onAuthed, initialError = '' }) {
  const [mode, setMode] = useState('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState(initialError);
  const [busy, setBusy] = useState(false);
  const emailRef = useRef(null);

  useEffect(() => { emailRef.current?.focus(); }, [mode]);

  const registering = mode === 'register';

  const submit = async (e) => {
    e.preventDefault();
    const next = {};
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) next.email = 'Enter a valid email address';
    if (!password) next.password = 'Enter your password';
    else if (registering && password.length < 8) next.password = 'Use at least 8 characters';
    setErrors(next);
    if (Object.keys(next).length) return;

    setBusy(true);
    setFormError('');
    try {
      const user = await (registering ? api.register : api.login)(email.trim(), password);
      onAuthed(user);
    } catch (err) {
      setFormError(err.message);
      setBusy(false);
    }
  };

  const err = (k) =>
    errors[k] && <p id={`auth-${k}-err`} className="mt-1 text-xs text-rose-600 dark:text-rose-400">{errors[k]}</p>;
  const aria = (k) => ({ 'aria-invalid': Boolean(errors[k]), 'aria-describedby': errors[k] ? `auth-${k}-err` : undefined });

  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center px-4 py-10">
      <div className="mb-6 flex items-center gap-3">
        <span className="grid h-10 w-10 place-items-center rounded-xl bg-emerald-600 text-white" aria-hidden="true">
          <CheckCheck className="h-5 w-5" />
        </span>
        <div>
          <h1 className="text-lg font-bold leading-tight">Bill Tracker</h1>
          <p className="text-xs text-stone-500 dark:text-stone-400">Your bills are private to your account.</p>
        </div>
      </div>

      <section className="card p-5" aria-labelledby="auth-h">
        <h2 id="auth-h" className="sr-only">{registering ? 'Create account' : 'Log in'}</h2>
        <div role="group" aria-label="Account" className="mb-5 grid grid-cols-2 rounded-lg border border-stone-300 p-0.5 dark:border-neutral-700">
          {MODES.map(([k, label]) => (
            <button
              key={k}
              type="button"
              aria-pressed={mode === k}
              onClick={() => { setMode(k); setErrors({}); setFormError(''); }}
              className={`rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors ${
                mode === k
                  ? 'bg-stone-900 text-white dark:bg-stone-100 dark:text-stone-900'
                  : 'text-stone-600 hover:bg-stone-100 dark:text-stone-300 dark:hover:bg-neutral-800'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        <form onSubmit={submit} noValidate className="space-y-4">
          <div>
            <label className="label" htmlFor="auth-email">Email</label>
            <input id="auth-email" ref={emailRef} type="email" className="input" value={email}
              onChange={(e) => setEmail(e.target.value)} autoComplete="email" maxLength={254} {...aria('email')} />
            {err('email')}
          </div>
          <div>
            <label className="label" htmlFor="auth-password">Password</label>
            <input id="auth-password" type="password" className="input" value={password}
              onChange={(e) => setPassword(e.target.value)} maxLength={128}
              autoComplete={registering ? 'new-password' : 'current-password'} {...aria('password')} />
            {err('password') || (registering && (
              <p className="mt-1 text-xs text-stone-500 dark:text-stone-400">At least 8 characters.</p>
            ))}
          </div>

          {formError && (
            <p role="alert" className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:bg-rose-950/40 dark:text-rose-200">
              {formError}
            </p>
          )}

          <button type="submit" className="btn-primary w-full justify-center" disabled={busy}>
            {busy ? 'Please wait…' : registering ? 'Create account' : 'Log in'}
          </button>
        </form>
      </section>
    </main>
  );
}
