import React from "react";

interface MarkdownRendererProps {
  content: string;
  className?: string;
}

/**
 * Parses markdown and inline formatting into rich React elements:
 * - `#`, `##`, `###` -> Enlarged, bold, styled section headings
 * - `**bold text**` -> <strong>bold text</strong>
 * - `*italic*` / `_italic_` -> <em>italic</em>
 * - `1. item` -> Ordered lists with bold lead-ins
 * - `- item` / `* item` -> Bullet lists with styled markers
 * - `code` -> Styled font-mono code badges
 */
export function MarkdownRenderer({ content, className = "" }: MarkdownRendererProps) {
  if (!content) return null;

  // Clean raw json_tell_me or trailing partial tokens if any leaked into the content
  const cleanText = content
    .replace(/```json_tell_me[\s\S]*?```/g, "")
    .replace(/`*json_tell[\s\S]*$/gi, "")
    .trim();

  // Split into lines
  const lines = cleanText.split("\n");
  const elements: React.ReactNode[] = [];

  let currentList: { type: "ul" | "ol"; items: React.ReactNode[] } | null = null;

  function flushList() {
    if (!currentList) return;
    if (currentList.type === "ul") {
      elements.push(
        <ul key={`ul-${elements.length}`} className="my-2 space-y-1.5 pl-4 list-disc text-ink-800 marker:text-amber-500">
          {currentList.items.map((item, idx) => (
            <li key={idx} className="leading-relaxed text-xs">
              {item}
            </li>
          ))}
        </ul>
      );
    } else {
      elements.push(
        <ol key={`ol-${elements.length}`} className="my-2 space-y-1.5 pl-4 list-decimal text-ink-800 marker:font-bold marker:text-ink-700">
          {currentList.items.map((item, idx) => (
            <li key={idx} className="leading-relaxed text-xs">
              {item}
            </li>
          ))}
        </ol>
      );
    }
    currentList = null;
  }

  function parseInline(text: string): React.ReactNode[] {
    const parts: React.ReactNode[] = [];
    // Regex for bold (**...**), code (`...`), and italic (*...*)
    const regex = /(\*\*.*?\*\*|`.*?`|\*.*?\*)/g;
    let lastIndex = 0;
    let match: RegExpExecArray | null;

    while ((match = regex.exec(text)) !== null) {
      if (match.index > lastIndex) {
        parts.push(text.substring(lastIndex, match.index));
      }
      const token = match[0];
      if (token.startsWith("**") && token.endsWith("**")) {
        parts.push(
          <strong key={`b-${match.index}`} className="font-bold text-ink-950">
            {token.slice(2, -2)}
          </strong>
        );
      } else if (token.startsWith("`") && token.endsWith("`")) {
        parts.push(
          <code
            key={`c-${match.index}`}
            className="rounded bg-ink-100 border border-ink-200 px-1 py-0.5 font-mono text-[11px] font-semibold text-amber-900"
          >
            {token.slice(1, -1)}
          </code>
        );
      } else if (token.startsWith("*") && token.endsWith("*")) {
        parts.push(
          <em key={`i-${match.index}`} className="italic text-ink-700">
            {token.slice(1, -1)}
          </em>
        );
      }
      lastIndex = match.index + token.length;
    }

    if (lastIndex < text.length) {
      parts.push(text.substring(lastIndex));
    }
    return parts.length > 0 ? parts : [text];
  }

  lines.forEach((rawLine, lineIndex) => {
    const line = rawLine.trim();

    if (!line) {
      flushList();
      return;
    }

    // Heading 1 (# Heading)
    if (line.startsWith("# ")) {
      flushList();
      const headingText = line.replace(/^#\s+/, "").replace(/\*\*/g, "");
      elements.push(
        <div key={`h1-${lineIndex}`} className="mt-4 mb-2 pb-1 border-b border-ink-200">
          <h2 className="text-sm font-black text-ink-950 tracking-tight uppercase flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-amber-500" />
            {headingText}
          </h2>
        </div>
      );
      return;
    }

    // Heading 2 (## Heading)
    if (line.startsWith("## ")) {
      flushList();
      const headingText = line.replace(/^##\s+/, "").replace(/\*\*/g, "");
      elements.push(
        <div key={`h2-${lineIndex}`} className="mt-3.5 mb-1.5">
          <h3 className="text-xs font-bold text-ink-900 tracking-wide uppercase flex items-center gap-1 text-amber-900">
            {headingText}
          </h3>
        </div>
      );
      return;
    }

    // Heading 3 (### Heading)
    if (line.startsWith("### ")) {
      flushList();
      const headingText = line.replace(/^###\s+/, "").replace(/\*\*/g, "");
      elements.push(
        <div key={`h3-${lineIndex}`} className="mt-3 mb-1">
          <h4 className="text-xs font-extrabold text-ink-950 flex items-center gap-1">
            {headingText}
          </h4>
        </div>
      );
      return;
    }

    // Unordered List (- or *)
    const ulMatch = line.match(/^[-*]\s+(.*)$/);
    if (ulMatch) {
      if (!currentList || currentList.type !== "ul") {
        flushList();
        currentList = { type: "ul", items: [] };
      }
      currentList.items.push(<>{parseInline(ulMatch[1])}</>);
      return;
    }

    // Ordered List (1. 2. 3.)
    const olMatch = line.match(/^(\d+)\.\s+(.*)$/);
    if (olMatch) {
      if (!currentList || currentList.type !== "ol") {
        flushList();
        currentList = { type: "ol", items: [] };
      }
      currentList.items.push(<>{parseInline(olMatch[2])}</>);
      return;
    }

    // Regular Paragraph
    flushList();
    elements.push(
      <p key={`p-${lineIndex}`} className="my-1.5 text-xs text-ink-800 leading-relaxed">
        {parseInline(line)}
      </p>
    );
  });

  flushList();

  return <div className={`space-y-1 ${className}`}>{elements}</div>;
}
