import { useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import Modal from './Modal';

const toText = (n) => (n == null ? '' : String(n));
const parse = (t) => {
  const s = t.replace(/[,\s₹]/g, '');
  if (s === '') return null;
  const n = Number(s);
  return Number.isFinite(n) && n >= 0 ? n : NaN;
};

/**
 * Edit per-category monthly targets. Categories that have spending but no target
 * are listed too, so setting one is a single step. Clearing a field removes the target.
 */
export default function BudgetsModal({ budgets, categories, onSave, onClose }) {
  const initial = new Map(budgets.map((b) => [b.category.toLowerCase(), b]));
  const [rows, setRows] = useState(() => {
    const out = budgets.map((b) => ({ category: b.category, text: toText(b.monthly_target), had: true }));
    for (const c of categories) {
      if (!initial.has(c.toLowerCase())) out.push({ category: c, text: '', had: false });
    }
    return out;
  });
  const [newCat, setNewCat] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const addCategory = (e) => {
    e.preventDefault();
    const name = newCat.trim();
    if (!name) return;
    if (rows.some((r) => r.category.toLowerCase() === name.toLowerCase())) {
      setError(`"${name}" is already in the list`);
      return;
    }
    setRows((r) => [...r, { category: name, text: '', had: false }]);
    setNewCat('');
    setError('');
  };

  const save = async () => {
    const upserts = [];
    const deletes = [];
    for (const r of rows) {
      const n = parse(r.text);
      if (Number.isNaN(n)) { setError(`"${r.category}" needs a number of 0 or more`); return; }
      const before = initial.get(r.category.toLowerCase());
      if (n == null) { if (before) deletes.push(r.category); }
      else if (!before || before.monthly_target !== n) upserts.push([r.category, n]);
    }
    setSaving(true);
    setError('');
    try {
      await onSave({ upserts, deletes });
    } catch (e) {
      setError(e.message);
      setSaving(false);
    }
  };

  return (
    <Modal title="Monthly category targets" onClose={onClose}>
      <p className="mb-4 text-sm text-stone-600 dark:text-stone-300">
        Set what you plan to spend per category each month. Leave a field empty for no target.
      </p>
      <ul className="space-y-2">
        {rows.map((r, i) => (
          <li key={r.category} className="flex items-center gap-2">
            <label htmlFor={`t-${i}`} className="min-w-0 flex-1 truncate text-sm font-medium">{r.category}</label>
            <div className="relative w-36">
              <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-stone-400">₹</span>
              <input
                id={`t-${i}`}
                className="input num pl-7 text-right"
                inputMode="decimal"
                placeholder="No target"
                value={r.text}
                onChange={(e) => setRows((rs) => rs.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))}
              />
            </div>
            <button
              className="btn-ghost p-1.5 text-stone-400 hover:text-rose-600"
              aria-label={`Clear target for ${r.category}`}
              title="Clear target"
              onClick={() => setRows((rs) => rs.map((x, j) => (j === i ? { ...x, text: '' } : x)))}
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </li>
        ))}
      </ul>

      <form onSubmit={addCategory} className="mt-4 flex gap-2 border-t border-stone-200 pt-4 dark:border-neutral-800">
        <input className="input" placeholder="New category (e.g. Health)" aria-label="New category name"
          value={newCat} onChange={(e) => setNewCat(e.target.value)} maxLength={60} />
        <button type="submit" className="btn-outline shrink-0"><Plus className="h-4 w-4" /> Add</button>
      </form>

      {error && (
        <p role="alert" className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-950/50 dark:text-rose-300">
          {error}
        </p>
      )}

      <div className="mt-5 flex justify-end gap-2">
        <button className="btn-outline" onClick={onClose}>Cancel</button>
        <button className="btn-primary" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save targets'}</button>
      </div>
    </Modal>
  );
}
