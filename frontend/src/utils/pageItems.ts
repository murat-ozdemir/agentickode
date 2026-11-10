// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: page buttons for Pagination, e.g. 1 … 4 5 6 … 12.

/** Page numbers to show around `current` (1-based); `null` marks a gap. */
export default function pageItems(current: number, totalPages: number, around = 1): (number | null)[] {
  const pages = new Set([1, totalPages]);
  for (let p = current - around; p <= current + around; p++) {
    if (p >= 1 && p <= totalPages) pages.add(p);
  }
  const sorted = [...pages].sort((a, b) => a - b);
  const items: (number | null)[] = [];
  sorted.forEach((p, i) => {
    const prev = sorted[i - 1];
    if (prev !== undefined && p - prev === 2) items.push(prev + 1);
    else if (prev !== undefined && p - prev > 2) items.push(null);
    items.push(p);
  });
  return items;
}
