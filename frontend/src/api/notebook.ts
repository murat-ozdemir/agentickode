// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch (loop efficiency item 7): the chain notebook of a run's PR.
import { get } from "./client";

export type NotebookKind = "decision" | "question" | "answer" | "run" | "ci";

export interface NotebookEntry {
  kind: NotebookKind;
  text: string;
  run_id: number | null;
  at: string;
}

export interface RunNotebook {
  pr_number: number | null;
  entries: NotebookEntry[];
}

export const getRunNotebook = (runId: number) => get<RunNotebook>(`/runs/${runId}/notebook`);
