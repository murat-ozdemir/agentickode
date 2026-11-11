// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

import { codexUsage, formatCredits } from "../../utils/codexUsage";

interface Props {
  metadata: Record<string, unknown> | null | undefined;
}

/** bimetri patch: ChatGPT plan credits and the cached-input share of a Codex call. */
export default function CodexUsageNote({ metadata }: Props) {
  const usage = codexUsage(metadata);
  if (!usage) return null;
  return (
    <span className="text-sky-400" data-testid="codex-usage">
      ChatGPT plan · {usage.credits != null ? `${formatCredits(usage.credits)} credits` : "credits n/a"}
      {usage.cachedIn != null && ` · ${usage.cachedIn.toLocaleString()} cached in`}
      {usage.reasoningOut ? ` · ${usage.reasoningOut.toLocaleString()} reasoning out` : ""}
    </span>
  );
}
