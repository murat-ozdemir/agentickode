// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: "Per page" choice for a paged list, remembered in this browser.
import { useState } from "react";

export const PAGE_SIZES = [10, 25, 50, 100];

function stored(key: string, sizes: number[]): number {
  try {
    const n = Number(window.localStorage.getItem(key));
    if (sizes.includes(n)) return n;
  } catch {
    // storage unavailable: use default
  }
  return sizes[0];
}

/** Page size for ``key`` (first of ``sizes`` by default) and a setter that saves the choice. */
export default function usePageSize(key: string, sizes: number[] = PAGE_SIZES) {
  const [size, setSize] = useState(() => stored(key, sizes));
  const choose = (n: number) => {
    setSize(n);
    try {
      window.localStorage.setItem(key, String(n));
    } catch {
      // storage unavailable: selection lasts until reload
    }
  };
  return [size, choose] as const;
}
