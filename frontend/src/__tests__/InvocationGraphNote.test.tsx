// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import InvocationGraphNote from "../components/runs/InvocationGraphNote";
import { graphOf } from "../components/graph/graphFormat";

const graph = {
  calls: 7,
  tools: { graph_read: 4, graph_continue: 1, fallback_rg: 2 },
  errors: 1,
  over_budget: 2,
  files: 5,
  returned_chars: 2_000,
  full_chars: 22_000,
  saved_tokens: 5_000,
};

describe("InvocationGraphNote", () => {
  it("shows calls per tool, budget overruns, failures and the saving", () => {
    render(<InvocationGraphNote metadata={{ model: "x", graph }} />);
    const note = screen.getByTestId("invocation-graph");
    expect(note).toHaveTextContent("Code graph: 7 calls");
    expect(note).toHaveTextContent("graph_read 4");
    expect(note).toHaveTextContent("2 over budget");
    expect(note).toHaveTextContent("1 failed");
    expect(note).toHaveTextContent("saved ≈ 5k tokens (91%)");
    expect(note).toHaveTextContent("sent 2k of 22k chars in 5 files");
  });

  it("renders nothing for a call without graph use", () => {
    const { container } = render(<InvocationGraphNote metadata={{ model: "x" }} />);
    expect(container).toBeEmptyDOMElement();
    expect(graphOf(null)).toBeNull();
    expect(graphOf({ graph: "x" })).toBeNull();
  });
});
