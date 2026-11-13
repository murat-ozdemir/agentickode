// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

import { useState } from "react";
import { Check, Copy } from "lucide-react";

interface CopyButtonProps {
  text: string;
}

/** bimetri patch: copies a chat answer's raw Markdown, like the claude.ai copy button. */
export default function CopyButton({ text }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setFailed(false);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (e) {
      console.error("Copy failed", e);
      setFailed(true);
    }
  };

  return (
    <button
      type="button"
      onClick={copy}
      data-testid="chat-copy"
      className="p-1 rounded text-gray-500 hover:text-gray-200 hover:bg-gray-700/60 transition-colors"
      title={failed ? "Copy failed" : copied ? "Copied" : "Copy"}
      aria-label="Copy answer"
    >
      {copied ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
    </button>
  );
}
