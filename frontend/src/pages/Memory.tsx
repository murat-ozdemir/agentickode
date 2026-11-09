// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: project memory page — proposals to review and the stored mem0 records.
import { useSearchParams } from "react-router-dom";
import MemoryRecords from "../components/memory/MemoryRecords";
import MemoryProposals from "./MemoryProposals";

const TABS = [
  { key: "proposals", label: "Proposals" },
  { key: "records", label: "Records" },
] as const;

export default function Memory() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "records" ? "records" : "proposals";

  return (
    <div className="space-y-6">
      <div className="flex gap-2 border-b border-gray-800" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={t.key === tab}
            onClick={() => setParams(t.key === "proposals" ? {} : { tab: t.key })}
            className={`px-3 py-2 text-sm -mb-px border-b-2 ${
              t.key === tab
                ? "border-blue-400 text-white"
                : "border-transparent text-gray-400 hover:text-white"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "records" ? <MemoryRecords /> : <MemoryProposals />}
    </div>
  );
}
