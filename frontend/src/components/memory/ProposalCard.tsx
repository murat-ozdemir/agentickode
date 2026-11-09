// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

import { useState } from "react";
import { Link } from "react-router-dom";
import { Check, Loader2, X } from "lucide-react";
import type { MemoryProposal, MemoryProposalKind } from "../../api";

interface Props {
  proposal: MemoryProposal;
  onApprove: (proposal: MemoryProposal, kind: MemoryProposalKind, text: string) => Promise<void>;
  onReject: (proposal: MemoryProposal) => Promise<void>;
}

const KINDS: MemoryProposalKind[] = ["lesson", "pitfall", "decision"];
const KIND_STYLE: Record<MemoryProposalKind, string> = {
  lesson: "bg-blue-900/40 text-blue-300",
  pitfall: "bg-amber-900/40 text-amber-300",
  decision: "bg-emerald-900/40 text-emerald-300",
};

export default function ProposalCard({ proposal, onApprove, onReject }: Props) {
  const [kind, setKind] = useState<MemoryProposalKind>(proposal.kind);
  const [text, setText] = useState(proposal.text);
  const [busy, setBusy] = useState(false);
  const pending = proposal.status === "pending";

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    try {
      await action();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      data-testid={`proposal-${proposal.id}`}
      className="bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-3"
    >
      <div className="flex items-center gap-3 text-xs text-gray-400">
        {pending ? (
          <select
            aria-label="Kind"
            value={kind}
            onChange={(e) => setKind(e.target.value as MemoryProposalKind)}
            className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-200"
          >
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        ) : (
          <span className={`px-2 py-0.5 rounded ${KIND_STYLE[proposal.kind]}`}>
            {proposal.kind}
          </span>
        )}
        <span className="font-mono">{proposal.project}</span>
        <span>{proposal.source === "agent" ? "Agent" : "Merge"}</span>
        {proposal.pr_number !== null && <span>PR #{proposal.pr_number}</span>}
        {proposal.run_id !== null && (
          <Link to={`/runs/${proposal.run_id}`} className="text-blue-400 hover:underline">
            Run #{proposal.run_id}
          </Link>
        )}
        {proposal.created_at && <span>{new Date(proposal.created_at).toLocaleString()}</span>}
      </div>
      {pending ? (
        <textarea
          aria-label="Text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={3}
          className="w-full bg-gray-800 border border-gray-700 rounded p-2 text-sm text-gray-100"
        />
      ) : (
        <p className="text-sm text-gray-200 whitespace-pre-wrap">{proposal.text}</p>
      )}
      {pending && (
        <div className="flex gap-2">
          <button
            onClick={() => run(() => onApprove(proposal, kind, text.trim()))}
            disabled={busy || !text.trim()}
            className="inline-flex items-center gap-1 px-3 py-1.5 rounded bg-emerald-700 hover:bg-emerald-600 text-white text-sm disabled:opacity-50"
          >
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
            Approve
          </button>
          <button
            onClick={() => run(() => onReject(proposal))}
            disabled={busy}
            className="inline-flex items-center gap-1 px-3 py-1.5 rounded bg-gray-800 hover:bg-gray-700 text-gray-200 text-sm disabled:opacity-50"
          >
            <X className="w-4 h-4" />
            Reject
          </button>
        </div>
      )}
    </div>
  );
}
