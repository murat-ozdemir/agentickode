// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: add, edit and delete hand-entered OpenAI credit top-ups.
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import { Pencil, Trash2, X } from "lucide-react";
import {
  addOpenAICredit,
  deleteOpenAICredit,
  getOpenAICredits,
  updateOpenAICredit,
  type OpenAICredit,
} from "../../api";

interface Props {
  onClose: () => void;
  onChanged: () => void;
}

const today = () => new Date().toISOString().slice(0, 10);

const field =
  "px-3 py-1.5 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500/40";

export default function OpenAICreditsModal({ onClose, onChanged }: Props) {
  const [credits, setCredits] = useState<OpenAICredit[]>([]);
  const [amount, setAmount] = useState("");
  const [day, setDay] = useState(today);
  const [editing, setEditing] = useState<number | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setCredits(await getOpenAICredits());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const reset = () => {
    setEditing(null);
    setAmount("");
    setDay(today());
  };

  const run = async (action: () => Promise<unknown>) => {
    try {
      await action();
      setError(null);
      reset();
      setDeleting(null);
      await load();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const body = { amount_usd: amount, credited_on: day };
    run(() => (editing == null ? addOpenAICredit(body) : updateOpenAICredit(editing, body)));
  };

  const edit = (c: OpenAICredit) => {
    setEditing(c.id);
    setAmount(c.amount_usd.toFixed(2));
    setDay(c.credited_on);
  };

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      role="dialog"
      aria-modal="true"
    >
      <div className="bg-gray-900 border border-gray-700/60 rounded-2xl p-6 w-full max-w-md shadow-2xl">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-white">OpenAI credits</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-white" aria-label="Close">
            <X className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={submit} className="flex flex-wrap items-end gap-2 mb-2">
          <label className="text-xs text-gray-400 flex flex-col gap-1">
            Amount (USD)
            <input
              type="number" step="0.01" min="0.01" required value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className={`${field} w-28`} data-testid="credit-amount"
            />
          </label>
          <label className="text-xs text-gray-400 flex flex-col gap-1">
            Date
            <input
              type="date" required value={day} onChange={(e) => setDay(e.target.value)}
              className={field} data-testid="credit-date"
            />
          </label>
          <button type="submit" className="px-3 py-1.5 text-sm text-white bg-blue-600 hover:bg-blue-500 rounded-lg" data-testid="credit-save">
            {editing == null ? "Add" : "Save"}
          </button>
          {editing != null && (
            <button type="button" onClick={reset} className="px-3 py-1.5 text-sm text-gray-400 hover:text-white">
              Cancel
            </button>
          )}
        </form>
        <p className="text-xs text-gray-500 mb-4">
          Enter the billing page's balance first, then each top-up.
        </p>
        {error && <p className="text-xs text-red-400 mb-3" data-testid="credit-error">{error}</p>}

        <ul className="divide-y divide-gray-800 max-h-64 overflow-y-auto" data-testid="credit-list">
          {credits.length === 0 && <li className="py-2 text-sm text-gray-500">No entries yet.</li>}
          {credits.map((c) => (
            <li key={c.id} className="py-2 flex items-center justify-between text-sm" data-testid={`credit-${c.id}`}>
              <span className="text-gray-400">{c.credited_on}</span>
              <span className="text-white font-medium">${c.amount_usd.toFixed(2)}</span>
              <span className="flex gap-2">
                <button onClick={() => edit(c)} aria-label="Edit" className="text-gray-500 hover:text-white" data-testid={`credit-edit-${c.id}`}>
                  <Pencil className="w-3.5 h-3.5" />
                </button>
                {deleting === c.id ? (
                  <button onClick={() => run(() => deleteOpenAICredit(c.id))} className="text-xs text-red-400" data-testid={`credit-confirm-${c.id}`}>
                    Delete?
                  </button>
                ) : (
                  <button onClick={() => setDeleting(c.id)} aria-label="Delete" className="text-gray-500 hover:text-red-400" data-testid={`credit-delete-${c.id}`}>
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>,
    document.body,
  );
}
