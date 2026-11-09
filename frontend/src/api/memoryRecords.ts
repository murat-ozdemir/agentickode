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

export const getMemoryRecords = (project: string, kind?: string) => {
  const params = new URLSearchParams({ project });
  if (kind) params.set("kind", kind);
  return get<MemoryRecord[]>(`/bimetri/memories?${params}`);
};
