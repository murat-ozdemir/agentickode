// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: read-only list of a project's mem0 records.
import { get } from "./client";

export interface MemoryRecord {
  id: string;
  text: string;
  kind: string | null;
  source: string | null;
  pr_number: number | null;
  date: string | null;
  created_at: string | null;
}

export interface MemoryRecordPage {
  items: MemoryRecord[];
  total: number;
  offset: number;
  limit: number;
  kinds: string[];
}

export const getMemoryRecords = (project: string, kind = "", offset = 0, limit = 50) => {
  const params = new URLSearchParams({ project, offset: String(offset), limit: String(limit) });
  if (kind) params.set("kind", kind);
  return get<MemoryRecordPage>(`/bimetri/memories?${params}`);
};
