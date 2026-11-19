// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

import DOMPurify from "dompurify";
import { marked } from "marked";

// bimetri patch: HTML only when the text starts with a tag (Plane sends `<p>...`). Markdown that
// merely contains a tag (e.g. `<pr_discussion>` in a fix-run description) must stay Markdown.
const HTML_TAG_PATTERN = /^\s*<[a-z][\s\S]*>/i;

/**
 * Renders a description string as sanitized HTML.
 *
 * - If the input starts with an HTML tag, it is sanitized directly with DOMPurify.
 * - Otherwise it is treated as Markdown, parsed with `marked`, then sanitized.
 *
 * Always sanitizes output to prevent XSS.
 */
export function renderDescription(text: string): string {
  const isHtml = HTML_TAG_PATTERN.test(text);

  if (isHtml) {
    return DOMPurify.sanitize(text);
  }

  const parsed = marked(text) as string;
  return DOMPurify.sanitize(parsed);
}
/**
 * bimetri patch: renders a chat answer (always Markdown, GFM tables, single newlines kept)
 * as sanitized HTML.
 */
export function renderChatMarkdown(text: string): string {
  const parsed = marked.parse(text, { gfm: true, breaks: true, async: false }) as string;
  return DOMPurify.sanitize(parsed);
}
