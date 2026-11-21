// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: read-only list of the selected project's mem0 records.
import { useEffect, useRef, useState } from "react";
import { getMemoryRecords, getProjects } from "../../api";
import type { MemoryRecordPage } from "../../api";
import usePageSize, { PAGE_SIZES } from "../../hooks/usePageSize";
import Pagination from "../shared/Pagination";
import { useToast } from "../shared/Toast";

const PAGE_SIZE_KEY = "memory.records.pageSize";
const EMPTY: MemoryRecordPage = { items: [], total: 0, offset: 0, limit: PAGE_SIZES[0], kinds: [] };

const SELECT =
  "bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200";

export default function MemoryRecords() {
  const toast = useToast();
  const toastRef = useRef(toast);
  toastRef.current = toast;
  const [projects, setProjects] = useState<string[]>([]);
  const [project, setProject] = useState("");
  const [kind, setKind] = useState("");
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = usePageSize(PAGE_SIZE_KEY);
  const [page, setPage] = useState<MemoryRecordPage>(EMPTY);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getProjects()
      .then((list) => {
        const names = list.map((p) => `${p.repo_owner}/${p.repo_name}`).sort();
        setProjects(names);
        setProject((current) => current || names[0] || "");
      })
      .catch((e) => toastRef.current.error(`Failed to load projects: ${(e as Error).message}`));
  }, []);

  useEffect(() => {
    if (!project) return;
    let stale = false;
    setLoading(true);
    getMemoryRecords(project, kind, offset, pageSize)
      .then((p) => !stale && setPage(p))
      .catch((e) => {
        if (stale) return;
        setPage(EMPTY);
        toastRef.current.error(`Failed to load records: ${(e as Error).message}`);
      })
      .finally(() => !stale && setLoading(false));
    return () => {
      stale = true;
    };
  }, [project, kind, offset, pageSize]);

  const selectProject = (value: string) => {
    setProject(value);
    setKind("");
    setOffset(0);
  };
  const selectKind = (value: string) => {
    setKind(value);
    setOffset(0);
  };
  const selectPageSize = (n: number) => {
    setPageSize(n);
    setOffset(0);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label="Project"
          value={project}
          onChange={(e) => selectProject(e.target.value)}
          className={SELECT}
        >
          {projects.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <select
          aria-label="Kind"
          value={kind}
          onChange={(e) => selectKind(e.target.value)}
          className={SELECT}
        >
          <option value="">All kinds</option>
          {page.kinds.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
        <span className="ml-auto text-sm text-gray-500">
          {loading ? "Loading..." : `${page.total} records`}
        </span>
      </div>
      {!loading && project && page.items.length === 0 && (
        <p className="text-gray-500 text-sm">No records.</p>
      )}
      <ul className="space-y-2">
        {page.items.map((r) => (
          <li
            key={r.id}
            data-testid={`record-${r.id}`}
            className="bg-gray-900 border border-gray-800 rounded p-3"
          >
            <div className="flex flex-wrap items-center gap-2 text-xs text-gray-400 mb-1">
              {r.kind && (
                <span className="px-2 py-0.5 rounded bg-gray-800 text-gray-200">{r.kind}</span>
              )}
              {r.pr_number !== null && <span>PR #{r.pr_number}</span>}
              {r.source && <span>{r.source}</span>}
              <span className="ml-auto">{r.date || r.created_at?.slice(0, 10)}</span>
            </div>
            <p className="text-sm text-gray-200 whitespace-pre-wrap">{r.text}</p>
          </li>
        ))}
      </ul>
      <Pagination
        total={page.total}
        offset={offset}
        limit={pageSize}
        onPageChange={setOffset}
        pageSizes={PAGE_SIZES}
        onLimitChange={selectPageSize}
      />
    </div>
  );
}
