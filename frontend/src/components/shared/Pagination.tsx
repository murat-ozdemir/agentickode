// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

import { useState } from "react";
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from "lucide-react";
import pageItems from "../../utils/pageItems";

interface Props {
  total: number;
  offset: number;
  limit: number;
  onPageChange: (newOffset: number) => void;
  /** Optional "Per page" selector; shown whenever there are runs. */
  pageSizes?: number[];
  onLimitChange?: (newLimit: number) => void;
}

const button =
  "px-2 py-1 rounded border border-gray-700/50 hover:bg-gray-800/40 disabled:opacity-30 disabled:cursor-not-allowed inline-flex items-center gap-1";

export default function Pagination({
  total,
  offset,
  limit,
  onPageChange,
  pageSizes,
  onLimitChange,
}: Props) {
  const [jump, setJump] = useState("");
  const showSizes = !!(pageSizes && onLimitChange && total > 0);
  if (total <= limit && !showSizes) return null;

  const currentPage = Math.floor(offset / limit) + 1;
  const totalPages = Math.max(1, Math.ceil(total / limit));
  const hasPrev = offset > 0;
  const hasNext = offset + limit < total;
  // bimetri patch: first/last, numbered pages and "Go to" page
  const goTo = (page: number) => onPageChange((Math.min(Math.max(page, 1), totalPages) - 1) * limit);

  const submitJump = () => {
    const page = Number(jump);
    if (Number.isInteger(page) && page > 0) goTo(page);
    setJump("");
  };

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 mt-4 text-sm text-gray-400">
      <span>
        {offset + 1}–{Math.min(offset + limit, total)} of {total}
      </span>
      <div className="flex flex-wrap items-center gap-2">
        {showSizes && (
          <label className="inline-flex items-center gap-1.5 mr-2 text-gray-500">
            Per page
            <select
              data-testid="page-size"
              value={limit}
              onChange={(e) => onLimitChange?.(Number(e.target.value))}
              className="bg-gray-900/40 border border-gray-700/50 rounded px-1.5 py-1 text-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-500/40"
            >
              {pageSizes?.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
        )}
        <button onClick={() => goTo(1)} disabled={!hasPrev} title="First page" aria-label="First page" className={button}>
          <ChevronsLeft className="w-3.5 h-3.5" />
        </button>
        <button onClick={() => goTo(currentPage - 1)} disabled={!hasPrev} className={button}>
          <ChevronLeft className="w-3.5 h-3.5" /> Previous
        </button>
        {pageItems(currentPage, totalPages).map((page, i) =>
          page === null ? (
            <span key={`gap-${i}`} className="px-1 text-gray-600">…</span>
          ) : (
            <button
              key={page}
              onClick={() => goTo(page)}
              aria-current={page === currentPage ? "page" : undefined}
              className={`min-w-[2rem] px-2 py-1 rounded border ${
                page === currentPage
                  ? "border-blue-500/60 bg-blue-500/15 text-blue-300"
                  : "border-gray-700/50 hover:bg-gray-800/40"
              }`}
              data-testid={`page-${page}`}
            >
              {page}
            </button>
          ),
        )}
        <span className="sr-only">
          Page {currentPage} of {totalPages}
        </span>
        <button onClick={() => goTo(currentPage + 1)} disabled={!hasNext} className={button}>
          Next <ChevronRight className="w-3.5 h-3.5" />
        </button>
        <button onClick={() => goTo(totalPages)} disabled={!hasNext} title="Last page" aria-label="Last page" className={button}>
          <ChevronsRight className="w-3.5 h-3.5" />
        </button>
        {totalPages > 1 && (
          <label className="inline-flex items-center gap-1.5 ml-2 text-gray-500">
            Go to
            <input
              type="number"
              min={1}
              max={totalPages}
              value={jump}
              onChange={(e) => setJump(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submitJump()}
              placeholder={String(currentPage)}
              className="w-16 bg-gray-900/40 border border-gray-700/50 rounded px-1.5 py-1 text-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-500/40"
              data-testid="page-jump"
            />
          </label>
        )}
      </div>
    </div>
  );
}
