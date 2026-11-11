// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: number of memory proposals waiting for review, for the Memory nav badge.
import { useEffect, useState } from "react";
import { getMemoryProposals } from "../api/memoryProposals";

const POLL_MS = 30_000;
const CHANGED = "bimetri:memory-proposals-changed";

/** Tell the badge that a proposal was approved or rejected, so it recounts at once. */
export const notifyMemoryProposalsChanged = () => window.dispatchEvent(new window.Event(CHANGED));

export default function useMemoryPendingCount(): number {
  const [count, setCount] = useState(0);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const pending = await getMemoryProposals("pending");
        if (alive) setCount(pending.length);
      } catch (e) {
        // keep the last count; the Memory page reports load errors itself
        console.warn("memory pending count:", e);
      }
    };
    load();
    const timer = setInterval(load, POLL_MS);
    window.addEventListener(CHANGED, load);
    return () => {
      alive = false;
      clearInterval(timer);
      window.removeEventListener(CHANGED, load);
    };
  }, []);

  return count;
}
