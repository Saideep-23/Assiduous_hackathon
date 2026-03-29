import DOMPurify from "isomorphic-dompurify";
import type { Config } from "dompurify";
import { marked } from "marked";
import React, { useMemo } from "react";

marked.use({
  gfm: true,
  breaks: true,
});

const PURIFY: Config = {
  ALLOWED_TAGS: [
    "p",
    "br",
    "strong",
    "em",
    "b",
    "i",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "ul",
    "ol",
    "li",
    "blockquote",
    "code",
    "pre",
    "a",
    "div",
    "span",
    "hr",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
  ],
  ALLOWED_ATTR: ["class", "href", "title", "id"],
  ALLOW_DATA_ATTR: false,
};

function sanitizeMemoHtml(raw: string): string {
  return DOMPurify.sanitize(raw, PURIFY);
}

export function MemoViewer({
  html,
  onAuditableClick: _onAuditableClick,
}: {
  html: string;
  /** Reserved for future auditable-value highlights */
  onAuditableClick?: (key: string) => void;
}) {
  const safeHtml = useMemo(() => {
    if (!html?.trim()) return "";
    const md = marked.parse(html, { async: false }) as string;
    return sanitizeMemoHtml(md);
  }, [html]);

  if (!html?.trim()) {
    return (
      <article className="memo-viewer memo-viewer--empty">
        <p className="memo-empty-title">No memo yet</p>
        <p className="memo-empty-copy">
          Run the agent to stream section-by-section drafting. The memo renders here when the SSE stream finishes with a
          final payload.
        </p>
      </article>
    );
  }

  return (
    <article
      className="memo-viewer"
      dangerouslySetInnerHTML={{ __html: safeHtml }}
    />
  );
}
