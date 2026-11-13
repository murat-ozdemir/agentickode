// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

import { describe, it, expect } from "vitest";
import { renderChatMarkdown, renderDescription } from "../utils/sanitize";

describe("renderDescription", () => {
  it("preserves HTML tags when input contains HTML", () => {
    const input = "<p>Hello <strong>world</strong></p>";
    const output = renderDescription(input);
    expect(output).toContain("<p>");
    expect(output).toContain("<strong>");
    expect(output).toContain("world");
  });

  it("converts markdown headings to h1 elements", () => {
    const input = "# My Heading";
    const output = renderDescription(input);
    expect(output).toContain("<h1>");
    expect(output).toContain("My Heading");
  });

  it("converts markdown bold to strong elements", () => {
    const input = "Some **bold** text";
    const output = renderDescription(input);
    expect(output).toContain("<strong>");
    expect(output).toContain("bold");
  });

  it("strips script tags to prevent XSS", () => {
    const input = '<p>Safe content</p><script>alert("xss")</script>';
    const output = renderDescription(input);
    expect(output).not.toContain("<script>");
    expect(output).not.toContain("alert");
    expect(output).toContain("Safe content");
  });

  it("strips javascript: hrefs to prevent XSS", () => {
    const input = '<a href="javascript:alert(1)">click me</a>';
    const output = renderDescription(input);
    expect(output).not.toContain("javascript:");
  });

  it("passes plain text through as a paragraph", () => {
    const input = "Just plain text with no markup";
    const output = renderDescription(input);
    expect(output).toContain("Just plain text with no markup");
  });

  it("handles markdown links correctly", () => {
    const input = "[Visit site](https://example.com)";
    const output = renderDescription(input);
    expect(output).toContain("<a");
    expect(output).toContain("https://example.com");
    expect(output).toContain("Visit site");
  });

  it("handles HTML with inline styles safely", () => {
    const input = '<p style="color: red">Styled text</p>';
    const output = renderDescription(input);
    expect(output).toContain("Styled text");
  });

  it("strips event handler attributes to prevent XSS", () => {
    const input = '<img src="x" onerror="alert(1)">';
    const output = renderDescription(input);
    expect(output).not.toContain("onerror");
  });
});
describe("renderChatMarkdown", () => {
  it("renders bold, lists and GFM tables from a chat answer", () => {
    const out = renderChatMarkdown(
      "**MCP** hazır\n\n- bir\n- iki\n\n| Sunucu | Adres |\n|---|---|\n| worker-1 | `192.168.20.10` |",
    );
    expect(out).toContain("<strong>MCP</strong>");
    expect(out).toContain("<li>bir</li>");
    expect(out).toContain("<table>");
    expect(out).toContain("<code>192.168.20.10</code>");
  });

  it("keeps single newlines as line breaks", () => {
    expect(renderChatMarkdown("[Using tool: a]\n[Using tool: b]")).toContain("<br>");
  });

  it("strips scripts and inline handlers", () => {
    const out = renderChatMarkdown('<img src=x onerror="alert(1)"><script>alert(2)</script>');
    expect(out).not.toContain("onerror");
    expect(out).not.toContain("<script");
  });
});
