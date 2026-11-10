// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import Pagination from "../components/shared/Pagination";
import pageItems from "../utils/pageItems";

const setup = (offset = 40) => {
  const onPageChange = vi.fn();
  render(<Pagination total={120} offset={offset} limit={10} onPageChange={onPageChange} />);
  return onPageChange;
};

describe("pageItems", () => {
  it("shows the ends and the pages around the current one", () => {
    expect(pageItems(5, 12)).toEqual([1, null, 4, 5, 6, null, 12]);
    expect(pageItems(1, 3)).toEqual([1, 2, 3]);
    expect(pageItems(4, 7)).toEqual([1, 2, 3, 4, 5, 6, 7]);
  });
});

describe("Pagination", () => {
  it("jumps to the first and last page", () => {
    const onPageChange = setup();
    fireEvent.click(screen.getByRole("button", { name: "First page" }));
    expect(onPageChange).toHaveBeenLastCalledWith(0);
    fireEvent.click(screen.getByRole("button", { name: "Last page" }));
    expect(onPageChange).toHaveBeenLastCalledWith(110);
  });

  it("marks the current page and opens a numbered one", () => {
    const onPageChange = setup();
    expect(screen.getByTestId("page-5")).toHaveAttribute("aria-current", "page");
    fireEvent.click(screen.getByTestId("page-12"));
    expect(onPageChange).toHaveBeenLastCalledWith(110);
  });

  it("goes to a typed page, clamped to the last one", () => {
    const onPageChange = setup();
    const input = screen.getByTestId("page-jump");
    fireEvent.change(input, { target: { value: "3" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onPageChange).toHaveBeenLastCalledWith(20);
    fireEvent.change(input, { target: { value: "99" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onPageChange).toHaveBeenLastCalledWith(110);
  });

  it("disables first and previous on the first page", () => {
    setup(0);
    expect(screen.getByRole("button", { name: "First page" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Previous/ })).toBeDisabled();
  });
});
