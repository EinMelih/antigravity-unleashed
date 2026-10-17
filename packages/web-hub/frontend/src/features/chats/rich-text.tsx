import { Fragment, type ReactNode } from "react";

export type RichTextLinkResolver = (href: string) => string | undefined;

function safeResolvedHref(href: string, resolveLink?: RichTextLinkResolver) {
  const resolved = /^https?:\/\//i.test(href) ? href : resolveLink?.(href);
  if (!resolved) return undefined;
  return /^https?:\/\//i.test(resolved) || /^\/(?!\/)/.test(resolved)
    ? resolved
    : undefined;
}

function inlineNodes(text: string, resolveLink?: RichTextLinkResolver): ReactNode[] {
  const pieces = text
    .split(/(\[[^\]]+\]\([^)]+\)|`[^`]+`|\*\*[^*]+\*\*)/g)
    .filter(Boolean);
  return pieces.map((piece, index) => {
    const link = piece.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (link) {
      const label = link[1] ?? "Link";
      const href = link[2] ?? "";
      const resolvedHref = safeResolvedHref(href, resolveLink);
      if (resolvedHref) {
        return <a href={resolvedHref} key={index} rel="noreferrer" target="_blank">{label}</a>;
      }
      return <code key={index}>{label}</code>;
    }
    if (piece.startsWith("`") && piece.endsWith("`")) {
      return <code key={index}>{piece.slice(1, -1)}</code>;
    }
    if (piece.startsWith("**") && piece.endsWith("**")) {
      return <strong key={index}>{inlineNodes(piece.slice(2, -2), resolveLink)}</strong>;
    }
    return <Fragment key={index}>{piece}</Fragment>;
  });
}

function tableCells(line: string) {
  const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return trimmed.split("|").map((cell) => cell.trim());
}

function isTableDivider(line: string) {
  const cells = tableCells(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

export function RichText({
  content,
  resolveLink,
}: {
  content: string | null | undefined;
  resolveLink?: RichTextLinkResolver;
}) {
  const lines = String(content ?? "").split(/\r?\n/);
  const nodes: ReactNode[] = [];
  let code: string[] | null = null;
  let list: { ordered: boolean; items: string[] } | null = null;

  const flushCode = () => {
    if (!code) return;
    nodes.push(
      <pre className="chat-code" key={`code-${nodes.length}`}>
        <code>{code.join("\n")}</code>
      </pre>,
    );
    code = null;
  };
  const flushList = () => {
    if (!list) return;
    const List = list.ordered ? "ol" : "ul";
    nodes.push(
      <List className="chat-markdown-list" key={`list-${nodes.length}`}>
        {list.items.map((item, index) => <li key={index}>{inlineNodes(item, resolveLink)}</li>)}
      </List>,
    );
    list = null;
  };

  for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
    const line = lines[lineIndex] ?? "";
    if (line.trim().startsWith("```")) {
      flushList();
      if (code) flushCode();
      else code = [];
      continue;
    }
    if (code) {
      code.push(line);
      continue;
    }
    const nextLine = lines[lineIndex + 1] ?? "";
    if (line.includes("|") && isTableDivider(nextLine)) {
      flushList();
      const headers = tableCells(line);
      const rows: string[][] = [];
      let rowIndex = lineIndex + 2;
      while (rowIndex < lines.length) {
        const rowLine = lines[rowIndex] ?? "";
        if (!rowLine.trim() || !rowLine.includes("|")) break;
        const cells = tableCells(rowLine);
        if (cells.length !== headers.length) break;
        rows.push(cells);
        rowIndex += 1;
      }
      nodes.push(
        <div className="chat-markdown-table-scroll" key={`table-${nodes.length}`}>
          <table className="chat-markdown-table">
            <thead>
              <tr>{headers.map((header, index) => (
                <th key={index} scope="col">{inlineNodes(header, resolveLink)}</th>
              ))}</tr>
            </thead>
            <tbody>{rows.map((row, rowNumber) => (
              <tr key={rowNumber}>{row.map((cell, cellNumber) => (
                <td key={cellNumber}>{inlineNodes(cell, resolveLink)}</td>
              ))}</tr>
            ))}</tbody>
          </table>
        </div>,
      );
      lineIndex = rowIndex - 1;
      continue;
    }
    const bullet = line.match(/^\s*[-*]\s+(.+)/);
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)/);
    if (bullet || ordered) {
      const isOrdered = Boolean(ordered);
      if (list && list.ordered !== isOrdered) flushList();
      list ??= { ordered: isOrdered, items: [] };
      list.items.push((bullet?.[1] ?? ordered?.[1]) || "");
      continue;
    }
    flushList();
    if (!line.trim()) {
      nodes.push(<span className="chat-paragraph-gap" key={`gap-${nodes.length}`} />);
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.+)/);
    if (heading) {
      const level = Math.min(4, (heading[1] ?? "#").length + 1);
      const Heading = `h${level}` as "h2" | "h3" | "h4" | "h5";
      nodes.push(<Heading key={`heading-${nodes.length}`}>{inlineNodes(heading[2] ?? "", resolveLink)}</Heading>);
      continue;
    }
    if (/^---+$/.test(line.trim())) {
      nodes.push(<hr key={`rule-${nodes.length}`} />);
      continue;
    }
    if (line.startsWith("> ")) {
      nodes.push(<blockquote key={`quote-${nodes.length}`}>{inlineNodes(line.slice(2), resolveLink)}</blockquote>);
      continue;
    }
    nodes.push(<p key={`paragraph-${nodes.length}`}>{inlineNodes(line, resolveLink)}</p>);
  }
  flushList();
  flushCode();
  return <div className="chat-rich-text">{nodes}</div>;
}
