// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: usage credits bought on top of the subscription — spent / monthly cap.
import type { QuotaCredits } from "../../api";
import { moneyText } from "./quotaFormat";

const FILL = { ok: "bg-emerald-500", warn: "bg-amber-500", hit: "bg-red-500" } as const;
const TEXT = { ok: "text-gray-200", warn: "text-amber-400", hit: "text-red-400" } as const;

function toneOf(c: QuotaCredits): keyof typeof FILL {
  if (c.limit_reached || (c.used_percent ?? 0) >= 100) return "hit";
  return (c.used_percent ?? 0) >= 70 ? "warn" : "ok";
}

export default function CreditsLine({ credits: c }: { credits: QuotaCredits }) {
  const tone = toneOf(c);
  const money = (n: number | null) => (n == null ? "—" : moneyText(n, c.currency));
  const amount = c.limit != null ? `${money(c.used)} / ${money(c.limit)}` : money(c.used);
  const title = [
    c.enabled ? "Usage credits on" : "Usage credits off",
    c.balance != null && `balance ${money(c.balance)}`,
    c.limit_reached && "monthly cap reached",
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div
      className={`flex items-center gap-2 text-xs ${c.enabled ? "" : "opacity-60"}`}
      title={title}
      data-testid="quota-credits"
    >
      <span className="w-12 shrink-0 text-gray-400">Credits</span>
      <div className="relative h-2 flex-1 rounded-full bg-gray-800">
        {c.used_percent != null && (
          <div
            className={`h-2 rounded-full ${FILL[tone]}`}
            style={{ width: `${Math.min(100, Math.max(0, c.used_percent))}%` }}
            data-testid="quota-credits-fill"
            data-tone={tone}
          />
        )}
      </div>
      <span
        className={`w-[7.5rem] shrink-0 truncate text-right font-medium ${TEXT[tone]}`}
        data-testid="quota-credits-amount"
      >
        {amount}
      </span>
    </div>
  );
}
