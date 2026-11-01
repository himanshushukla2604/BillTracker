import { useEffect } from 'react';

export default function Toast({ toast, onDismiss }) {
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(onDismiss, toast.undo ? 7000 : 4000);
    return () => clearTimeout(t);
  }, [toast, onDismiss]);

  if (!toast) return null;
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-4 z-[60] flex justify-center px-4">
      <div
        role={toast.error ? 'alert' : 'status'}
        className={`pointer-events-auto flex max-w-md items-center gap-3 rounded-xl px-4 py-3 text-sm shadow-lg ${
          toast.error ? 'bg-rose-600 text-white' : 'bg-stone-900 text-white dark:bg-stone-100 dark:text-stone-900'
        }`}
      >
        <span>{toast.msg}</span>
        {toast.undo && (
          <button
            className="font-semibold underline underline-offset-2"
            onClick={() => { toast.undo(); onDismiss(); }}
          >
            Undo
          </button>
        )}
      </div>
    </div>
  );
}
