/**
 * @file DirectStatusLine.tsx
 * @description A status line component that renders directly to the terminal
 * using ANSI escape sequences, bypassing Ink's render cycle to prevent flickering.
 *
 * This approach is based on the recommendation from the Ink flickering investigation:
 * https://github.com/atxtechbro/test-ink-flickering
 *
 * The key insight is that Ink regenerates the complete UI output on every React
 * state change. By rendering the frequently-updating status line directly to the
 * terminal with absolute cursor positioning, we bypass this limitation.
 */

import { useEffect, useRef, useCallback } from "react";
import { Box } from "ink";

// ANSI escape sequences
const ANSI = {
  // Cursor positioning
  saveCursor: "\x1b7",           // Save cursor position (DEC)
  restoreCursor: "\x1b8",        // Restore cursor position (DEC)
  moveTo: (row: number, col: number) => `\x1b[${row};${col}H`,
  moveToColumn: (col: number) => `\x1b[${col}G`,
  cursorUp: (n: number) => `\x1b[${n}A`,
  cursorDown: (n: number) => `\x1b[${n}B`,

  // Line operations
  clearLine: "\x1b[2K",          // Clear entire line
  clearToEndOfLine: "\x1b[K",    // Clear from cursor to end of line

  // Colors (SGR - Select Graphic Rendition)
  reset: "\x1b[0m",
  bold: "\x1b[1m",
  dim: "\x1b[2m",

  // Foreground colors
  colors: {
    black: "\x1b[30m",
    red: "\x1b[31m",
    green: "\x1b[32m",
    yellow: "\x1b[33m",
    blue: "\x1b[34m",
    magenta: "\x1b[35m",
    cyan: "\x1b[36m",
    white: "\x1b[37m",
    gray: "\x1b[90m",
    grey: "\x1b[90m",
  } as Record<string, string>,

  // Hide/show cursor
  hideCursor: "\x1b[?25l",
  showCursor: "\x1b[?25h",
};

// Spinner animation frames
const triangleFrames = ["◸", "◹", "◿", "◺", "◸", "◹", "◿", "◺"];
const barFrames = [
  "▰▱▱▱▱▱▱",
  "▰▰▱▱▱▱▱",
  "▰▰▰▱▱▱▱",
  "▰▰▰▰▱▱▱",
  "▰▰▰▰▰▱▱",
  "▰▰▰▰▰▰▱",
  "▰▰▰▰▰▰▰",
  "▱▰▰▰▰▰▰",
  "▱▱▰▰▰▰▰",
  "▱▱▱▰▰▰▰",
  "▱▱▱▱▰▰▰",
  "▱▱▱▱▱▰▰",
  "▱▱▱▱▱▱▰",
  "▱▱▱▱▱▱▱",
];

export interface DirectStatusLineProps {
  /** The text to display */
  text: string;
  /** Color for the status line (default: magenta) */
  color?: string;
  /** Whether the status line is active/visible */
  isActive: boolean;
  /** Update interval in ms (default: 100) */
  updateInterval?: number;
}

/**
 * DirectStatusLine renders an animated status line directly to the terminal,
 * bypassing Ink's render cycle to prevent flickering.
 *
 * It uses a placeholder Box to reserve space in the Ink layout, then renders
 * the animated content directly to stdout using ANSI escape sequences.
 */
export function DirectStatusLine({
  text,
  color = "magenta",
  isActive,
  updateInterval = 100,
}: DirectStatusLineProps) {
  const triangleIndexRef = useRef(0);
  const barIndexRef = useRef(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastRenderedRef = useRef<string>("");

  // Get the ANSI color code
  const colorCode = ANSI.colors[color] || ANSI.colors.magenta;

  // Render function that writes directly to stdout
  const renderStatusLine = useCallback(() => {
    if (!isActive) return;

    const triangle = triangleFrames[triangleIndexRef.current];
    const bar = barFrames[barIndexRef.current];

    // Build the status line string with ANSI codes
    const statusLine =
      `${colorCode}${ANSI.bold}${triangle}${ANSI.reset} ` +
      `${colorCode}${ANSI.bold}${text}${ANSI.reset} ` +
      `${colorCode}${ANSI.dim}${bar}${ANSI.reset}`;

    // Only render if content changed (reduces writes)
    if (statusLine === lastRenderedRef.current) return;
    lastRenderedRef.current = statusLine;

    // Save cursor, move to the placeholder position, clear line, write, restore cursor
    // We use carriage return + clear to end approach for simplicity
    const output =
      ANSI.saveCursor +           // Save current cursor position
      `\r` +                       // Move to beginning of current line (placeholder line)
      ANSI.clearLine +            // Clear the entire line
      statusLine +                // Write the status
      ANSI.restoreCursor;         // Restore cursor position

    // Write directly to stdout, bypassing Ink
    process.stdout.write(output);
  }, [text, colorCode, isActive]);

  // Clear the status line when deactivating
  const clearStatusLine = useCallback(() => {
    const output =
      ANSI.saveCursor +
      `\r` +
      ANSI.clearLine +
      ANSI.restoreCursor;
    process.stdout.write(output);
    lastRenderedRef.current = "";
  }, []);

  // Set up the animation interval
  useEffect(() => {
    if (!isActive) {
      // Clear any existing interval
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      clearStatusLine();
      return;
    }

    // Initial render
    renderStatusLine();

    // Animation loop - single interval that advances both animations
    intervalRef.current = setInterval(() => {
      triangleIndexRef.current = (triangleIndexRef.current + 1) % triangleFrames.length;
      barIndexRef.current = (barIndexRef.current + 1) % barFrames.length;
      renderStatusLine();
    }, updateInterval);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      clearStatusLine();
    };
  }, [isActive, renderStatusLine, clearStatusLine, updateInterval]);

  // Re-render when text changes
  useEffect(() => {
    if (isActive) {
      lastRenderedRef.current = ""; // Force re-render
      renderStatusLine();
    }
  }, [text, isActive, renderStatusLine]);

  // Render a placeholder box that reserves space in Ink's layout
  // This ensures the status line has its own line in the terminal
  if (!isActive) {
    return null;
  }

  // Return an empty placeholder that reserves the line
  // The actual content is rendered directly to stdout
  return (
    <Box height={1}>
      {/* Empty placeholder - actual content rendered via stdout */}
    </Box>
  );
}

/**
 * Hook for using direct terminal rendering outside of React components.
 * Useful for updating status from async operations.
 */
export function useDirectStatusLine() {
  const activeRef = useRef(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const triangleIndexRef = useRef(0);
  const barIndexRef = useRef(0);
  const textRef = useRef("");
  const colorRef = useRef("magenta");

  const render = useCallback(() => {
    if (!activeRef.current) return;

    const colorCode = ANSI.colors[colorRef.current] || ANSI.colors.magenta;
    const triangle = triangleFrames[triangleIndexRef.current];
    const bar = barFrames[barIndexRef.current];

    const statusLine =
      `${colorCode}${ANSI.bold}${triangle}${ANSI.reset} ` +
      `${colorCode}${ANSI.bold}${textRef.current}${ANSI.reset} ` +
      `${colorCode}${ANSI.dim}${bar}${ANSI.reset}`;

    const output =
      ANSI.saveCursor +
      `\r` +
      ANSI.clearLine +
      statusLine +
      ANSI.restoreCursor;

    process.stdout.write(output);
  }, []);

  const start = useCallback((text: string, color = "magenta") => {
    textRef.current = text;
    colorRef.current = color;
    activeRef.current = true;

    render();

    intervalRef.current = setInterval(() => {
      triangleIndexRef.current = (triangleIndexRef.current + 1) % triangleFrames.length;
      barIndexRef.current = (barIndexRef.current + 1) % barFrames.length;
      render();
    }, 100);
  }, [render]);

  const update = useCallback((text: string, color?: string) => {
    textRef.current = text;
    if (color) colorRef.current = color;
    render();
  }, [render]);

  const stop = useCallback(() => {
    activeRef.current = false;
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    // Clear the line
    const output =
      ANSI.saveCursor +
      `\r` +
      ANSI.clearLine +
      ANSI.restoreCursor;
    process.stdout.write(output);
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stop();
    };
  }, [stop]);

  return { start, update, stop };
}
