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
export function MarkdownRenderer({ children }: { children: string }) {
  const rendered = useMemo(() => {
    // First, trim the input to remove any leading/trailing whitespace
    const trimmedInput = children.trim();
    
    if (!trimmedInput) {
      return '';
    }
    
    try {
      // Configure marked to use terminal renderer
      marked.setOptions({
        renderer: new TerminalRenderer(),
      });
      // Parse and render markdown
      const result = marked.parse(trimmedInput);
      // Aggressively remove all leading whitespace, newlines, and carriage returns
      // This ensures no blank line appears at the start
      const cleaned = result.replace(/^[\s\n\r]+/, '').replace(/[\s\n\r]+$/, '');
      return cleaned.trim();
    } catch {
      // Fallback to plain text if markdown parsing fails
      return trimmedInput;
    }
  }, [children]);

  return <Text>{rendered}</Text>;
}
