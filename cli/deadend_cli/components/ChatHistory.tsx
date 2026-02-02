import { Box, Text } from "ink";
import { useMemo, memo } from "react";
import type { Message } from "../types/message.ts";
import { ChatMessage } from "./ChatMessage.tsx";

export interface ChatHistoryProps {
  messages: Message[];
  /** Maximum number of messages to display (auto-calculated if not provided) - currently unused, all messages are shown */
  maxVisible?: number;
  /** Static messages that are rendered via Static component at app level */
  staticMessages?: Message[];
  /** Dynamic messages that are rendered normally */
  dynamicMessages?: Message[];
}

function ChatHistoryComponent({ messages, staticMessages, dynamicMessages }: ChatHistoryProps) {
  // If staticMessages and dynamicMessages are provided, use them (for Static component usage)
  // Otherwise, render all messages normally
  const messagesToRender = useMemo(() => {
    if (staticMessages !== undefined && dynamicMessages !== undefined) {
      return { static: staticMessages, dynamic: dynamicMessages };
    }
    // Fallback: render all messages as dynamic
    return { static: [], dynamic: messages };
  }, [messages, staticMessages, dynamicMessages]);

  // Render dynamic messages
  const dynamicElements = useMemo(() => {
    return messagesToRender.dynamic.map((message) => (
      <ChatMessage key={message.id} message={message} />
    ));
  }, [
    messagesToRender.dynamic.length,
    messagesToRender.dynamic.length > 0 ? messagesToRender.dynamic[messagesToRender.dynamic.length - 1]?.id : null
  ]);

  // Show all messages - no truncation
  // Static messages are handled at app level, we only render dynamic ones here
  return (
    <Box flexDirection="column">
      {/* Dynamic messages - last few that might still be updating */}
      {dynamicElements}

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

// Memoize ChatHistory to prevent re-renders when props haven't meaningfully changed
export const ChatHistory = memo(ChatHistoryComponent, (prevProps, nextProps) => {
  // Only re-render if:
  // 1. Message count changed
  // 2. Dynamic messages changed (check by last message ID)
  // 3. Static messages changed (check by count)
  const prevDynamicLastId = prevProps.dynamicMessages?.[prevProps.dynamicMessages.length - 1]?.id;
  const nextDynamicLastId = nextProps.dynamicMessages?.[nextProps.dynamicMessages.length - 1]?.id;
  const prevStaticCount = prevProps.staticMessages?.length ?? 0;
  const nextStaticCount = nextProps.staticMessages?.length ?? 0;
  
  const dynamicChanged = prevDynamicLastId !== nextDynamicLastId;
  const staticChanged = prevStaticCount !== nextStaticCount;
  const messageCountChanged = prevProps.messages.length !== nextProps.messages.length;
  
  // Re-render only if something meaningful changed
  return !(dynamicChanged || staticChanged || messageCountChanged);
});
