// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

import { useCallback, useEffect, useRef, useState } from "react";
import { LayoutDashboard, Search, X } from "lucide-react";
import { getAnalytics, getRuns, getStats } from "../api";
import type { DistributionFilter } from "../api";
import { BASE } from "../api/client";
import TaskDistributionCard from "../components/distribution/TaskDistributionCard";
import AnalyticsCharts from "../components/shared/AnalyticsCharts";
import FilterBar from "../components/shared/FilterBar";
import OpenAIBalanceCard from "../components/shared/OpenAIBalanceCard";
import OpenAISpendChart from "../components/shared/OpenAISpendChart";
import Pagination from "../components/shared/Pagination";
import StatsBar from "../components/shared/StatsBar";
import TaskRunTable from "../components/runs/TaskRunTable";
import useOpenAIUsage from "../hooks/useOpenAIUsage";
import type { AnalyticsSummary, Stats, TaskRun } from "../types";

// bimetri: sayfa basina kosu sayisi secilebilir; secim tarayicida hatirlanir
const PAGE_SIZES = [10, 25, 50, 100];
const PAGE_SIZE_KEY = "dashboard.pageSize";

function initialPageSize(): number {
  try {
    const n = Number(window.localStorage.getItem(PAGE_SIZE_KEY));
    if (PAGE_SIZES.includes(n)) return n;
  } catch {
    // storage unavailable: use default
  }
  return PAGE_SIZES[0];
}

export default function Dashboard() {
  const [runs, setRuns] = useState<TaskRun[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<Stats | null>(null);
  const [analytics, setAnalytics] = useState<AnalyticsSummary | null>(null);
  const openai = useOpenAIUsage();
  const [filter, setFilter] = useState("");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(initialPageSize);
  const [sortBy, setSortBy] = useState("created_at");
  const [sortOrder, setSortOrder] = useState("desc");
  const [dist, setDist] = useState<DistributionFilter | null>(null);

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search);
      setOffset(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  // Reset offset when filter changes
  useEffect(() => { setOffset(0); }, [filter, dist]);

  const load = useCallback(async () => {
    const [r, s, a] = await Promise.all([
      getRuns({
        status: filter || undefined,
        search: debouncedSearch || undefined,
        sort_by: sortBy,
        sort_order: sortOrder,
        limit: pageSize,
        offset,
        dist_dim: dist?.dim,
        dist_value: dist?.value,
        dist_range: dist?.range,
      }),
      getStats(),
      getAnalytics(),
    ]);
    // bimetri: the result shrank below this page (live update): move to the last page
    if (offset > 0 && offset >= r.total) {
      setOffset(Math.max(0, Math.ceil(r.total / pageSize) - 1) * pageSize);
      return;
    }
    setRuns(r.items);
    setTotal(r.total);
    setStats(s);
    setAnalytics(a);
  }, [filter, debouncedSearch, sortBy, sortOrder, offset, pageSize, dist]);

  const handlePageSize = (n: number) => {
    setPageSize(n);
    setOffset(0);
    try {
      window.localStorage.setItem(PAGE_SIZE_KEY, String(n));
    } catch {
      // storage unavailable: selection lasts until reload
    }
  };

  // Initial load + SSE
  useEffect(() => {
    load();
  }, [load]);

  // SSE live updates
  const eventSourceRef = useRef<EventSource | null>(null);
  useEffect(() => {
    const es = new EventSource(`${BASE}/runs/stream`);
    eventSourceRef.current = es;
    es.onmessage = () => {
      // Re-fetch on any event
      load();
    };
    es.onerror = () => {
      // On SSE error, fall back to polling
      es.close();
      const interval = setInterval(load, 5000);
      return () => clearInterval(interval);
    };
    return () => es.close();
  }, [load]);

  const handleSort = (column: string) => {
    if (sortBy === column) {
      setSortOrder((prev) => (prev === "desc" ? "asc" : "desc"));
    } else {
      setSortBy(column);
      setSortOrder("desc");
    }
  };

  return (
    <>
      <h1 className="text-xl font-semibold mb-6 flex items-center gap-2">
        <LayoutDashboard className="w-5 h-5 text-blue-400" />
        Dashboard
      </h1>
      <StatsBar stats={stats} />
      <AnalyticsCharts
        data={analytics}
        extraMetric={<OpenAIBalanceCard usage={openai} />}
        extraChart={<OpenAISpendChart data={openai.data} />}
      />
      <TaskDistributionCard onSelect={setDist} />
      <div className="flex flex-wrap items-center gap-3 mb-5">
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search runs..."
            className="w-full pl-9 pr-3 py-2 bg-gray-900/40 border border-gray-800/60 rounded-xl text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/40 backdrop-blur-sm"
          />
        </div>
        {dist && (
          <button
            type="button"
            onClick={() => setDist(null)}
            data-testid="distribution-filter"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs bg-blue-500/15 border border-blue-500/40 text-blue-200 hover:bg-blue-500/25"
          >
            {dist.dim}: {dist.value} · {dist.range === "all" ? "All" : dist.range}
            <X className="w-3.5 h-3.5" aria-label="Clear filter" />
          </button>
        )}
      </div>
      <FilterBar value={filter} onChange={setFilter} />
      <TaskRunTable
        runs={runs}
        sortBy={sortBy}
        sortOrder={sortOrder}
        onSort={handleSort}
      />
      <Pagination
        total={total}
        offset={offset}
        limit={pageSize}
        onPageChange={setOffset}
        pageSizes={PAGE_SIZES}
        onLimitChange={handlePageSize}
      />
    </>
  );
}