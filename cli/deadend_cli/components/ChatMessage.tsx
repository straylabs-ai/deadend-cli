/**
 * @file ChatMessage.tsx
 * @description Chat message rendering with a consistent two-column layout.
 *
 * Layout pattern (inspired by Letta Code):
 *
 *   [2-char indicator] [content]
 *   [5-char prefix   ] [nested result]
 *
 * Indicator column uses BlinkDot for tool states, unicode symbols
 * for other message types, and keeps a consistent left gutter so
 * the entire transcript feels aligned.
 */

import { Box, Text } from "ink";
import { memo } from "react";
import type { Message } from "../types/message.ts";
import { MarkdownRenderer } from "./MarkdownRenderer.tsx";
import { BlinkDot } from "./BlinkDot.tsx";
import { colors } from "./colors.ts";
import type {
  ToolCallStartData,
  ToolCallEndData,
  AgentThoughtData,
  AgentEndData,
  AgentErrorData,
  LogMessageData,
} from "../types/rpc.ts";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Wrap long text into multiple lines */
function wrapText(str: string, maxLineLen: number, maxLines = 10): string {
  const lines: string[] = [];
  let remaining = str;

  while (remaining.length > 0 && lines.length < maxLines) {
    if (remaining.length <= maxLineLen) {
      lines.push(remaining);
      break;
    }
    let breakPoint = remaining.lastIndexOf(" ", maxLineLen);
    if (breakPoint <= 0) breakPoint = maxLineLen;
    lines.push(remaining.slice(0, breakPoint));
    remaining = remaining.slice(breakPoint).trimStart();
  }

  if (remaining.length > 0 && lines.length >= maxLines) {
    lines[lines.length - 1] += "...";
  }
  return lines.join("\n");
}

/** Truncate a string */
function truncate(str: string, maxLen: number): string {
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen - 3) + "...";
}

// ---------------------------------------------------------------------------
// Shared layout primitives
// ---------------------------------------------------------------------------

/** Two-column row: 2-char indicator + content */
function Row({
  indicator,
  children,
}: {
  indicator: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Box flexDirection="row">
      <Box width={2} flexShrink={0}>
        {indicator}
      </Box>
      <Box flexGrow={1} flexDirection="column">
        {children}
      </Box>
    </Box>
  );
}

/** Nested result line with "  \u23BF  " (⎿) prefix */
function ResultRow({ children }: { children: React.ReactNode }) {
  return (
    <Box flexDirection="row">
      <Box width={5} flexShrink={0}>
        <Text dimColor>{"  \u23BF  "}</Text>
      </Box>
      <Box flexGrow={1}>{children}</Box>
    </Box>
  );
}

// ---------------------------------------------------------------------------
// Message renderer
// ---------------------------------------------------------------------------

function ChatMessageComponent({ message }: { message: Message }) {
  // --- User messages (highlighted text) ---
  if (message.role === "user") {
    return (
      <Box marginBottom={1}>
        <Text backgroundColor="#2d2d2d" bold>{"\u276F"}</Text>
        <Text backgroundColor="#2d2d2d"> {message.content} </Text>
      </Box>
    );
  }

  // --- Event-based messages ---
  switch (message.type) {
    case "event_tool_call":
      return <ToolCallMessage message={message} />;

    case "event_agent_thought":
      return <AgentThoughtMessage message={message} />;

    case "event_agent_start":
      return (
        <Box marginBottom={1}>
          <Row indicator={<BlinkDot color={colors.message.agentStart} animate />}>
            <Text color={colors.message.agentStart} bold>
              {" "}{message.content}
            </Text>
          </Row>
        </Box>
      );

    case "event_agent_end":
      return <AgentEndMessage message={message} />;

    case "event_agent_error":
      return <AgentErrorMessage message={message} />;

    case "event_agent_routed":
      return (
        <Box marginBottom={1}>
          <Row indicator={<Text color={colors.message.routing}>{"\u25CB"}</Text>}>
            <Text color={colors.message.routing}>
              {" "}{message.content}
            </Text>
          </Row>
        </Box>
      );

    case "event_log":
      return <LogMessage message={message} />;

    case "error":
      return (
        <Box marginBottom={1} flexDirection="column">
          <Row indicator={<Text color={colors.status.error}>{"\u26A0"}</Text>}>
            <Text color={colors.status.error}> </Text>
          </Row>
          <ResultRow>
            <MarkdownRenderer>{message.content}</MarkdownRenderer>
          </ResultRow>
        </Box>
      );

    case "info":
      return (
        <Box marginBottom={1}>
          <Row indicator={<Text color={colors.status.info}>{"\u25CF"}</Text>}>
            <Box marginLeft={1}>
              <MarkdownRenderer>{message.content}</MarkdownRenderer>
            </Box>
          </Row>
        </Box>
      );

    case "command":
      return (
        <Box marginBottom={1}>
          <Row indicator={<Text color={colors.message.command}>{"\u276F"}</Text>}>
            <Text color={colors.message.command}> {message.content}</Text>
          </Row>
        </Box>
      );

    // Default text messages (assistant, system)
    default: {
      const isAssistant = message.role === "assistant";
      return (
        <Box marginBottom={1} flexDirection="column">
          <Row
            indicator={
              <Text color={isAssistant ? colors.message.assistant : colors.text.secondary}>
                {"\u25CF"}
              </Text>
            }
          >
            {isAssistant && (
              <Text color={colors.accent} bold> AI</Text>
            )}
          </Row>
          <ResultRow>
            <MarkdownRenderer>{message.content}</MarkdownRenderer>
          </ResultRow>
        </Box>
      );
    }
  }
}

// ---------------------------------------------------------------------------
// Tool call
// ---------------------------------------------------------------------------

function ToolCallMessage({ message }: { message: Message }) {
  const event = message.eventData;

  if (!event) {
    return (
      <Box marginBottom={1}>
        <Row indicator={<BlinkDot color={colors.dot.running} animate />}>
          <Text color="cyan" bold> {message.content}</Text>
        </Row>
      </Box>
    );
  }

  // --- tool_call_start ---
  if (event.type === "tool_call_start") {
    const data = event.data as unknown as ToolCallStartData;
    const argsDisplay = data.args ? wrapText(data.args, 100, 12) : "";

    return (
      <Box flexDirection="column" marginBottom={1}>
        <Row indicator={<BlinkDot color={colors.dot.running} animate />}>
          <Text bold> {data.tool_name}</Text>
        </Row>
        {argsDisplay && (
          <ResultRow>
            <Text color={colors.text.secondary}>{argsDisplay}</Text>
          </ResultRow>
        )}
      </Box>
    );
  }

  // --- tool_call_end ---
  if (event.type === "tool_call_end") {
    const data = event.data as unknown as ToolCallEndData;
    const dotColor = data.success ? colors.dot.completed : colors.dot.error;
    const statusIcon = data.success ? "\u2713" : "\u2717"; // ✓ / ✗
    const duration = data.duration_ms ? ` (${data.duration_ms.toFixed(0)}ms)` : "";

    let resultText = data.error || "";
    if (!resultText && data.result) {
      resultText = wrapText(data.result, 100, 15);
    }

    return (
      <Box flexDirection="column" marginBottom={1}>
        <Row indicator={<BlinkDot color={dotColor} />}>
          <Text bold color={dotColor}>
            {" "}{statusIcon} {data.tool_name}
          </Text>
          <Text dimColor>{duration}</Text>
        </Row>
        {resultText && (
          <ResultRow>
            <Text color={data.error ? colors.status.error : colors.text.secondary}>
              {resultText}
            </Text>
          </ResultRow>
        )}
      </Box>
    );
  }

  return null;
}

// ---------------------------------------------------------------------------
// Agent thought (dimmed, with ✻ marker)
// ---------------------------------------------------------------------------

function AgentThoughtMessage({ message }: { message: Message }) {
  const data = message.eventData?.data as unknown as AgentThoughtData | undefined;
  const displayText = data?.thought || data?.summary || message.content;

  return (
    <Box flexDirection="column" marginBottom={1}>
      <Row indicator={<Text dimColor>{"✻"}</Text>}>
        <Text dimColor bold>{" Thoughts…"}</Text>
      </Row>
      <ResultRow>
        <Box>
          <MarkdownRenderer dimColor>{displayText}</MarkdownRenderer>
        </Box>
      </ResultRow>
    </Box>
  );
}

// ---------------------------------------------------------------------------
// Agent end (clean card, no heavy rules)
// ---------------------------------------------------------------------------

function AgentEndMessage({ message }: { message: Message }) {
  const data = message.eventData?.data as unknown as AgentEndData | undefined;
  const confidence = data?.confidence_score
    ? Math.round(data.confidence_score * 100)
    : null;
  const isHigh = confidence !== null && confidence >= 80;
  const dotColor = isHigh ? colors.status.success : colors.status.warning;

  return (
    <Box flexDirection="column" marginY={1}>
      <Row indicator={<BlinkDot color={dotColor} />}>
        <Text color={dotColor} bold>
          {" "}{message.eventData?.agent_name || "agent"}
          {confidence !== null && (
            <Text color={dotColor}> {"\u2014"} {confidence}%</Text>
          )}
        </Text>
      </Row>
      {data?.notes && (
        <ResultRow>
          <Text>{wrapText(data.notes, 80, 5)}</Text>
        </ResultRow>
      )}
    </Box>
  );
}

// ---------------------------------------------------------------------------
// Agent error
// ---------------------------------------------------------------------------

function AgentErrorMessage({ message }: { message: Message }) {
  const data = message.eventData?.data as unknown as AgentErrorData | undefined;

  return (
    <Box flexDirection="column" marginY={1}>
      <Row indicator={<Text color={colors.status.error}>{"\u2717"}</Text>}>
        <Text color={colors.status.error} bold>
          {" "}{data?.error_type || "Error"}
        </Text>
      </Row>
      <ResultRow>
        <Text color={colors.status.error}>
          {wrapText(data?.error_message || message.content, 80, 5)}
        </Text>
      </ResultRow>
    </Box>
  );
}

// ---------------------------------------------------------------------------
// Log message
// ---------------------------------------------------------------------------

function LogMessage({ message }: { message: Message }) {
  const data = message.eventData?.data as unknown as LogMessageData | undefined;
  const level = data?.level || "info";

  const levelColor =
    (colors.log as Record<string, string>)[level] || colors.log.info;
  const isDimmed = level === "debug";

  return (
    <Box marginBottom={0}>
      <Row
        indicator={
          <Text color={levelColor} dimColor={isDimmed}>
            {"\u22EF"}
          </Text>
        }
      >
        <Text color={levelColor} dimColor={isDimmed}>
          {" "}{truncate(data?.message || message.content, 90)}
        </Text>
      </Row>
    </Box>
  );
}

// ---------------------------------------------------------------------------
// Memoized export
// ---------------------------------------------------------------------------

export const ChatMessage = memo(ChatMessageComponent, (prev, next) => {
  if (prev.message.id !== next.message.id) return false;
  const contentChanged = prev.message.content !== next.message.content;
  const timestampChanged =
    prev.message.timestamp.getTime() !== next.message.timestamp.getTime();
  const eventDataChanged = prev.message.eventData !== next.message.eventData;
  return !(contentChanged || timestampChanged || eventDataChanged);
});
