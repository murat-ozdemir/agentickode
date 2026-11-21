// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: pace, colour and countdown helpers for the subscription limit bars.
import type { QuotaWindow } from "../../api";

export type QuotaTone = "ok" | "warn" | "hit";

/** Share of the window already elapsed (0-100), or null when its length or reset is unknown. */
export function pacePercent(w: QuotaWindow, now: number = Date.now()): number | null {
  if (!w.minutes || !w.resets_at) return null;
  const left = (new Date(w.resets_at).getTime() - now) / 60_000;
  return Math.min(100, Math.max(0, 100 - (left / w.minutes) * 100));
}

/** Red at the limit; amber from 70% or when usage runs 10 points ahead of the clock. */
export function toneOf(w: QuotaWindow, now: number = Date.now()): QuotaTone {
  if (w.used_percent >= 100) return "hit";
  const pace = pacePercent(w, now);
  if (w.used_percent >= 70 || (pace != null && w.used_percent > pace + 10)) return "warn";
  return "ok";
}

/** "2h 05m", "3d 4h" or "<1m" until ``iso``. */
export function untilText(iso: string, now: number = Date.now()): string {
  const mins = Math.max(0, Math.round((new Date(iso).getTime() - now) / 60_000));
  if (mins < 1) return "<1m";
  const days = Math.floor(mins / 1440);
  const hours = Math.floor((mins % 1440) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${String(mins % 60).padStart(2, "0")}m`;
  return `${mins}m`;
}

export const PROVIDER_LABELS: Record<string, string> = { claude: "Claude", codex: "Codex" };

export const providerLabel = (p: string) =>
  PROVIDER_LABELS[p] ?? p.charAt(0).toUpperCase() + p.slice(1);

/** Time only for today, day/month and time otherwise. */
export function shortTime(iso: string): string {
  const d = new Date(iso);
  const time = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === new Date().toDateString()) return time;
  return `${d.toLocaleDateString("en-GB", { day: "2-digit", month: "2-digit" })} ${time}`;
}
