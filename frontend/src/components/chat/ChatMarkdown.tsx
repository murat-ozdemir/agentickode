// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

import { renderChatMarkdown } from "../../utils/sanitize";
import CopyButton from "./CopyButton";

interface ChatMarkdownProps {
  text: string;
}

/** bimetri patch: shows an agent's chat answer as rendered Markdown, with a copy button. */
export default function ChatMarkdown({ text }: ChatMarkdownProps) {
  return (
    <div>
      <div
        className="chat-md"
        data-testid="chat-markdown"
        // Safe: renderChatMarkdown() sanitizes via DOMPurify
        dangerouslySetInnerHTML={{ __html: renderChatMarkdown(text) }}
      />
      <div className="mt-1.5 -mb-1 flex justify-end">
        <CopyButton text={text} />
      </div>
    </div>
  );
}
