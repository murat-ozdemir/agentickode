// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

import { ClipboardList, Eye, FlaskConical, Wrench } from "lucide-react";
import type { ElementType } from "react";

// bimetri: run kind (task / test / fix / review), styled like StatusBadge
const colors: Record<string, string> = {
  task: "bg-sky-900/50 text-sky-300 border-sky-700",
  test: "bg-teal-900/50 text-teal-300 border-teal-700",
  fix: "bg-amber-900/50 text-amber-300 border-amber-700",
  review: "bg-fuchsia-900/50 text-fuchsia-300 border-fuchsia-700",
};

const icons: Record<string, ElementType> = {
  task: ClipboardList,
  test: FlaskConical,
  fix: Wrench,
  review: Eye,
};

export default function RunKindBadge({ kind }: { kind: string }) {
  const cls = colors[kind] ?? "bg-gray-800 text-gray-300 border-gray-600";
  const Icon = icons[kind];
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded border ${cls}`}>
      {Icon && <Icon className="w-3 h-3" />}
      {kind}
    </span>
  );
}
