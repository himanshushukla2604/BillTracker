import { useEffect, useRef, useState } from 'react';
import { Pencil, Search, Trash2 } from 'lucide-react';
import { api } from '../lib/api';
import { money, parseISO } from '../lib/format';
import { paidWith } from '../lib/payment';
import Modal from './Modal';

const dateWithYear = (iso) => parseISO(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });

/** Find an expense in any month by name, category, who paid you back, or card, then edit or delete it.
 *  The query lives in the parent so the results come back after an edit closes. */
export default function SearchModal({ query, onQueryChange, cards, onEdit, onDelete, onClose }) {
  const [results, setResults] = useState(null); // null until the first answer for this query
  const [error, setError] = useState('');
  const [confirmId, setConfirmId] = useState(null);
  const [reload, setReload] = useState(0);
  const inputRef = useRef(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  useEffect(() => {
    const q = query.trim();
    if (!q) { setResults(null); setError(''); return undefined; }
    let stale = false;
    const t = setTimeout(async () => {
      try {
        const found = await api.search(q);
        if (!stale) { setResults([...found].reverse()); setError(''); } // newest first
      } catch (e) {
        if (!stale) setError(e.message);
      }
    }, 250);
    return () => { stale = true; clearTimeout(t); };
  }, [query, reload]);

  const remove = async (e) => {
    setConfirmId(null);
    await onDelete(e);
    setReload((n) => n + 1);
  };

  const total = results?.reduce((s, e) => s + e.amount, 0) ?? 0;

  return (
    <Modal title="Search expenses" onClose={onClose}>
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-stone-400" />
        <input
          ref={inputRef}
          type="search"
          className="input pl-9"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          placeholder="Name, category, card or person"
          aria-label="Search expenses"
          maxLength={100}
        />
      </div>

      {error && <p role="alert" className="mt-3 text-sm text-rose-600 dark:text-rose-400">{error}</p>}
      {!query.trim() && (
        <p className="mt-4 text-sm text-stone-500 dark:text-stone-400">Searches every month, newest first.</p>
      )}
      {results && results.length === 0 && (
        <p className="mt-4 text-sm text-stone-500 dark:text-stone-400">Nothing matches “{query.trim()}”.</p>
      )}
      {results && results.length > 0 && (
        <>
          <p className="num mt-3 text-xs text-stone-500 dark:text-stone-400" aria-live="polite">
            {results.length} found · {money(total)}
          </p>
          <ul className="mt-1 divide-y divide-stone-100 dark:divide-neutral-800" aria-label="Search results">
            {results.map((e) => (
              <li key={e.id} className="flex items-center gap-2 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{e.name}</p>
                  <p className="truncate text-xs text-stone-500 dark:text-stone-400">
                    {dateWithYear(e.due_date)} · {e.category}
                    {paidWith(e, cards) && ` · ${paidWith(e, cards)}`}
                  </p>
                </div>
                <span className="num shrink-0 text-sm font-semibold">{money(e.amount)}</span>
                <button className="btn-ghost p-1.5" onClick={() => onEdit(e)} aria-label={`Edit ${e.name}`} title="Edit">
                  <Pencil className="h-4 w-4" />
                </button>
                {confirmId === e.id ? (
                  <button className="btn bg-rose-600 px-2 py-1 text-xs text-white hover:bg-rose-700" onClick={() => remove(e)}>
                    Confirm delete
                  </button>
                ) : (
                  <button className="btn-ghost p-1.5 text-stone-500 hover:text-rose-600" onClick={() => setConfirmId(e.id)}
                    aria-label={`Delete ${e.name}`} title="Delete">
                    <Trash2 className="h-4 w-4" />
                  </button>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </Modal>
  );
}
