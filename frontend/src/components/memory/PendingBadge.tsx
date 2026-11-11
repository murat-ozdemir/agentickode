// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: count bubble on the Memory nav link; nothing while no proposal waits.
interface PendingBadgeProps {
  count: number;
  inline?: boolean; // in a full-width row (mobile menu): at the row's end, not over the corner
}

export default function PendingBadge({ count, inline = false }: PendingBadgeProps) {
  if (count <= 0) return null;
  return (
    <span
      data-testid="memory-pending-badge"
      title={`${count} memory proposal${count === 1 ? "" : "s"} waiting for review`}
      className={`${inline ? "ml-auto" : "absolute -top-1.5 -right-1.5"} min-w-[1.125rem] h-[1.125rem] px-1 rounded-full bg-amber-500 text-gray-950 text-[10px] font-bold leading-[1.125rem] text-center`}
    >
      {count > 99 ? "99+" : count}
    </span>
  );
}
