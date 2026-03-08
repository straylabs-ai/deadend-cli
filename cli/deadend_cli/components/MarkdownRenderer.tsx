import { Text } from "ink";
import { useMemo } from "react";
import { marked } from "marked";
import TerminalRenderer from "marked-terminal";

/**
 * Markdown renderer component for terminal output.
 * 
 * Renders markdown content using marked and marked-terminal for
 * terminal-friendly formatting. Falls back to plain text if parsing fails.
 */
export function MarkdownRenderer({ children, dimColor = false }: { children: string; dimColor?: boolean }) {
  const rendered = useMemo(() => {
    // First, trim the input to remove any leading/trailing whitespace
    const trimmedInput = children.trim();
    
    if (!trimmedInput) {
      return '';
    }
    
    try {
      // Configure marked to use terminal renderer
      const renderer = new TerminalRenderer();
      marked.setOptions({
        renderer: renderer,
      });
      // Parse and render markdown (sync: we don't use async extensions)
      const result = marked.parse(trimmedInput) as string;
      // Remove horizontal rule lines (lines with only dashes, underscores, or asterisks)
      // This removes separator lines like "---" or "___" that marked-terminal creates
      const withoutHorizontalRules = result
        .split('\n')
        .filter((line: string) => {
          const trimmed = line.trim();
          // Filter out lines that are only dashes, underscores, asterisks, or spaces
          return !/^[-_*=\s]+$/.test(trimmed);
        })
        .join('\n');
      // Aggressively remove all leading whitespace, newlines, and carriage returns
      // This ensures no blank line appears at the start
      const cleaned = withoutHorizontalRules.replace(/^[\s\n\r]+/, '').replace(/[\s\n\r]+$/, '');
      return cleaned.trim();
    } catch {
      // Fallback to plain text if markdown parsing fails
      return trimmedInput;
    }
  }, [children]);

  return <Text dimColor={dimColor}>{rendered}</Text>;
}
