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
import Pagination from "../components/shared/Pagination";
import { useToast } from "../components/shared/Toast";
import { notifyMemoryProposalsChanged } from "../hooks/useMemoryPendingCount";
import usePageSize, { PAGE_SIZES } from "../hooks/usePageSize";

const STATUSES: MemoryProposalStatus[] = ["pending", "approved", "rejected"];
const PAGE_SIZE_KEY = "memory.proposals.pageSize";

export default function MemoryProposals() {
  const toast = useToast();
  // the toast API object changes on every provider render; keep it out of load's deps
  const toastRef = useRef(toast);
  toastRef.current = toast;
  const [status, setStatus] = useState<MemoryProposalStatus>("pending");
  const [project, setProject] = useState("");
  const [items, setItems] = useState<MemoryProposal[]>([]);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = usePageSize(PAGE_SIZE_KEY);

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
  // The API returns every proposal of a status; page them here so the project filter sees all.
  // After the last card of the last page is approved/rejected, fall back to the new last page.
  const lastPage = Math.max(0, Math.ceil(shown.length / pageSize) - 1);
  const start = offset < shown.length ? offset : lastPage * pageSize;
  const page = shown.slice(start, start + pageSize);
  const selectStatus = (s: MemoryProposalStatus) => {
    setStatus(s);
    setOffset(0);
  };
  const selectProject = (value: string) => {
    setProject(value);
    setOffset(0);
  };
  const selectPageSize = (n: number) => {
    setPageSize(n);
    setOffset(0);
  };

  const approve = async (
    p: MemoryProposal,
    kind: MemoryProposalKind,
    text: string,
    replaces: string | null,
  ) => {
    try {
      const replacesChanged = replaces !== (p.replaces_mem0_id ?? null);
      if (kind !== p.kind || text !== p.text || replacesChanged) {
        await updateMemoryProposal(p.id, {
          kind,
          text,
          ...(replacesChanged ? { replaces_mem0_id: replaces } : {}),
        });
      }
      await approveMemoryProposal(p.id);
      const saved = replaces ? "Updated a project memory record" : "Saved to project memory";
      toast.success(p.pr_number !== null ? `${saved} (PR #${p.pr_number})` : saved);
      setItems((all) => all.filter((x) => x.id !== p.id));
      notifyMemoryProposalsChanged();
    } catch (e) {
      toast.error(`Approve failed: ${(e as Error).message}`);
    }
  };

  const reject = async (p: MemoryProposal) => {
    try {
      await rejectMemoryProposal(p.id);
      setItems((all) => all.filter((x) => x.id !== p.id));
      notifyMemoryProposalsChanged();
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
            Lessons, pitfalls and decisions proposed from merged PRs or by agents during a run. Approved ones are saved
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
            onClick={() => selectStatus(s)}
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
          onChange={(e) => selectProject(e.target.value)}
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
        {page.map((p) => (
          <ProposalCard key={p.id} proposal={p} onApprove={approve} onReject={reject} />
        ))}
      </div>
      <Pagination
        total={shown.length}
        offset={start}
        limit={pageSize}
        onPageChange={setOffset}
        pageSizes={PAGE_SIZES}
        onLimitChange={selectPageSize}
      />
    </div>
  );
}
