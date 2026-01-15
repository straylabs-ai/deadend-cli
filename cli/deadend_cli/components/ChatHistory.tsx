import { Box, Text, useStdout } from "ink";
import { useState, useEffect, useMemo } from "react";
import type { Message } from "../types/message.ts";
import { ChatMessage } from "./ChatMessage.tsx";

export interface ChatHistoryProps {
  messages: Message[];
  /** Maximum number of messages to display (auto-calculated if not provided) */
  maxVisible?: number;
}

// Estimate lines per message type
function estimateMessageLines(message: Message): number {
  switch (message.type) {
    case "event_tool_call":
      return 18; // Tool name + args (12) + result (15) headers
    case "event_agent_thought":
      return 27; // Header + 25 lines of content
    case "event_agent_end":
    case "event_agent_error":
      return 6; // Separator + content + separator
    case "event_log":
      return 1; // Compact log line
    default:
      return 2; // Timestamp + content
  }
}

export function ChatHistory({ messages, maxVisible }: ChatHistoryProps) {
  const { stdout } = useStdout();
  const [scrollOffset, setScrollOffset] = useState(0);

  // Calculate available height for messages
  // Reserve space for: Banner (~6), StatusArea (~2), InputArea (~3)
  const terminalRows = stdout?.rows || 24;
  const reservedRows = 11; // Banner + Status + Input + padding
  const availableRows = Math.max(terminalRows - reservedRows, 12);

  // Calculate how many messages can fit
  const calculatedMaxVisible = useMemo(() => {
    if (maxVisible) return maxVisible;

    // Estimate based on average lines per message
    let totalLines = 0;
    let count = 0;

    // Count from the end (most recent messages)
    for (let i = messages.length - 1; i >= 0 && totalLines < availableRows; i--) {
      totalLines += estimateMessageLines(messages[i]);
      if (totalLines <= availableRows) {
        count++;
      }
    }

    return Math.max(count, 3); // At least 3 messages
  }, [messages, availableRows, maxVisible]);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (messages.length > calculatedMaxVisible) {
      setScrollOffset(messages.length - calculatedMaxVisible);
    } else {
      setScrollOffset(0);
    }
  }, [messages.length, calculatedMaxVisible]);

  // Get visible messages
  const visibleMessages = useMemo(() => {
    const start = Math.max(0, scrollOffset);
    const end = start + calculatedMaxVisible;
    return messages.slice(start, end);
  }, [messages, scrollOffset, calculatedMaxVisible]);

  const hiddenAbove = scrollOffset;
  const hiddenBelow = Math.max(0, messages.length - scrollOffset - calculatedMaxVisible);

  return (
    <Box flexDirection="column" flexGrow={1}>
      {/* Hidden messages indicator (above) */}
      {hiddenAbove > 0 && (
        <Box marginBottom={1}>
          <Text color="gray" dimColor>
            ↑ {hiddenAbove} more message{hiddenAbove !== 1 ? "s" : ""} above
          </Text>
        </Box>
      )}

      {/* Visible messages */}
      <Box flexDirection="column" flexGrow={1}>
        {visibleMessages.map((message) => (
          <ChatMessage key={message.id} message={message} />
        ))}
      </Box>

      {/* Hidden messages indicator (below) - shouldn't appear with auto-scroll */}
      {hiddenBelow > 0 && (
        <Box marginTop={1}>
          <Text color="gray" dimColor>
            ↓ {hiddenBelow} more message{hiddenBelow !== 1 ? "s" : ""} below
          </Text>
        </Box>
      )}

      {/* Empty state */}
      {messages.length === 0 && (
        <Box>
          <Text color="gray" dimColor>
            No messages yet. Type a command or message to get started.
          </Text>
        </Box>
      )}
    </Box>
  );
}
