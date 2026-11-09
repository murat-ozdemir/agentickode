// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: memory proposals made on PR merge, reviewed before they reach mem0.
import { BASE, get, post } from "./client";

export type MemoryProposalKind = "lesson" | "pitfall" | "decision";
export type MemoryProposalStatus = "pending" | "approved" | "rejected";

export interface MemoryProposal {
  id: number;
  project: string;
  pr_number: number;
  kind: MemoryProposalKind;
  text: string;
  status: MemoryProposalStatus;
  mem0_id: string | null;
  created_at: string | null;
  decided_at: string | null;
}

const PATH = "/bimetri/memory-proposals";

export const getMemoryProposals = (status?: MemoryProposalStatus, project?: string) => {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (project) params.set("project", project);
  const query = params.toString();
  return get<MemoryProposal[]>(query ? `${PATH}?${query}` : PATH);
};

export async function updateMemoryProposal(
  id: number,
  body: { kind?: MemoryProposalKind; text?: string },
): Promise<MemoryProposal> {
  const res = await fetch(`${BASE}${PATH}/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(typeof detail.detail === "string" ? detail.detail : `${res.status}`);
  }
  return res.json();
}

export const approveMemoryProposal = (id: number) =>
  post<MemoryProposal>(`${PATH}/${id}/approve`);

export const rejectMemoryProposal = (id: number) =>
  post<MemoryProposal>(`${PATH}/${id}/reject`);
