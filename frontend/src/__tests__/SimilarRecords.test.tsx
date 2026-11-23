// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import SimilarRecords from "../components/memory/SimilarRecords";

describe("SimilarRecords", () => {
  it("tells a pending proposal with no matches apart from one never checked", () => {
    const { rerender } = render(
      <SimilarRecords records={[]} replaces={null} onReplacesChange={vi.fn()} />,
    );
    expect(screen.getByTestId("similar-records-empty")).toHaveTextContent(
      "No similar records in memory",
    );
    rerender(<SimilarRecords records={null} replaces={null} onReplacesChange={vi.fn()} />);
    expect(screen.getByTestId("similar-records-empty")).toHaveTextContent(
      "Not checked against memory",
    );
  });

  it("shows nothing on a decided proposal without records", () => {
    const { container } = render(<SimilarRecords records={null} replaces={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
