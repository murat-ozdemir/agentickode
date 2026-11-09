// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: review project-memory proposals made on PR merge.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Brain, RefreshCw } from "lucide-react";
import {
  approveMemoryProposal,
  getMemoryProposals,
  rejectMemoryProposal,
  updateMemoryProposal,
} from "../api";
import type { MemoryProposal, MemoryProposalKind, MemoryProposalStatus } from "../api";
import ProposalCard from "../components/memory/ProposalCard";
import { useToast } from "../components/shared/Toast";

const STATUSES: MemoryProposalStatus[] = ["pending", "approved", "rejected"];

export default function MemoryProposals() {
  const toast = useToast();
  // the toast API object changes on every provider render; keep it out of load's deps
  const toastRef = useRef(toast);
  toastRef.current = toast;
  const [status, setStatus] = useState<MemoryProposalStatus>("pending");
  const [project, setProject] = useState("");
  const [items, setItems] = useState<MemoryProposal[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await getMemoryProposals(status));
    } catch (e) {
      toastRef.current.error(`Failed to load proposals: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => {
    load();
  }, [load]);

  const projects = useMemo(() => [...new Set(items.map((p) => p.project))].sort(), [items]);
  const shown = project ? items.filter((p) => p.project === project) : items;

  const approve = async (p: MemoryProposal, kind: MemoryProposalKind, text: string) => {
    try {
      if (kind !== p.kind || text !== p.text) await updateMemoryProposal(p.id, { kind, text });
      await approveMemoryProposal(p.id);
      toast.success(`Saved to project memory (PR #${p.pr_number})`);
      setItems((all) => all.filter((x) => x.id !== p.id));
    } catch (e) {
      toast.error(`Approve failed: ${(e as Error).message}`);
    }
  };

  const reject = async (p: MemoryProposal) => {
    try {
      await rejectMemoryProposal(p.id);
      setItems((all) => all.filter((x) => x.id !== p.id));
    } catch (e) {
      toast.error(`Reject failed: ${(e as Error).message}`);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white inline-flex items-center gap-2">
            <Brain className="w-6 h-6 text-blue-400" />
            Memory proposals
          </h1>
          <p className="text-sm text-gray-400 mt-1">
            Lessons, pitfalls and decisions proposed from merged PRs. Approved ones are saved
            to the project memory (mem0) and used in future runs.
          </p>
        </div>
        <button
          onClick={load}
          aria-label="Refresh"
          className="p-2 rounded hover:bg-gray-800 text-gray-400"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {STATUSES.map((s) => (
          <button
            key={s}
            onClick={() => setStatus(s)}
            className={`px-3 py-1.5 rounded text-sm capitalize ${
              s === status ? "bg-gray-800 text-white" : "text-gray-400 hover:text-white"
            }`}
          >
            {s}
          </button>
        ))}
        <select
          aria-label="Project"
          value={project}
          onChange={(e) => setProject(e.target.value)}
          className="ml-auto bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200"
        >
          <option value="">All projects</option>
          {projects.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </div>
      {!loading && shown.length === 0 && (
        <p className="text-gray-500 text-sm">No {status} proposals.</p>
      )}
      <div className="space-y-3">
        {shown.map((p) => (
          <ProposalCard key={p.id} proposal={p} onApprove={approve} onReject={reject} />
        ))}
      </div>
    </div>
  );
}
