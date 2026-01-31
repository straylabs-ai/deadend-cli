import { useState, useCallback, useRef, useEffect } from "react";
import type { AgentEvent, EventType } from "../types/rpc.ts";
import type { DeadEndRpcClient } from "../lib/deadend-rpc-client.ts";

export interface UseEventStreamOptions {
  /** Filter events by type - only these types will be collected */
  filter?: EventType[];
  /** Maximum number of events to keep in memory */
  maxEvents?: number;
  /** Callback for each event */
  onEvent?: (event: AgentEvent) => void;
}

export interface UseEventStreamReturn {
  /** List of collected events */
  events: AgentEvent[];
  /** Whether the event stream is connected */
  isConnected: boolean;
  /** Current error, if any */
  error: Error | null;
  /** Start subscribing to events */
  subscribe: () => void;
  /** Stop subscribing to events */
  unsubscribe: () => void;
  /** Clear all collected events */
  clearEvents: () => void;
  /** Get events of a specific type */
  getEventsByType: (type: EventType) => AgentEvent[];
  /** Get the latest event */
  latestEvent: AgentEvent | null;
}

export function useEventStream(
  rpcClient: DeadEndRpcClient | null,
  options: UseEventStreamOptions = {}
): UseEventStreamReturn {
  const { filter, maxEvents = 100, onEvent } = options;

  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);
  const isSubscribedRef = useRef(false);

  const clearEvents = useCallback(() => {
    setEvents([]);
  }, []);

  const addEvent = useCallback(
    (event: AgentEvent) => {
      // Filter by type if specified
      if (filter && filter.length > 0 && !filter.includes(event.type)) {
        return;
      }

      // Call the onEvent callback
      if (onEvent) {
        onEvent(event);
      }

      setEvents((prev) => {
        const newEvents = [...prev, event];
        // Keep only the last maxEvents
        if (newEvents.length > maxEvents) {
          return newEvents.slice(-maxEvents);
        }
        return newEvents;
      });
    },
    [filter, maxEvents, onEvent]
  );

  const subscribe = useCallback(() => {
    if (!rpcClient || isSubscribedRef.current) {
      return;
    }

    isSubscribedRef.current = true;
    abortControllerRef.current = new AbortController();
    setIsConnected(true);
    setError(null);

    const runSubscription = async () => {
      try {
        const { generator, abort } = rpcClient.subscribeEvents();
        try {
          for await (const event of generator) {
            if (abortControllerRef.current?.signal.aborted) {
              abort();
              break;
            }
            addEvent(event);
          }
        } catch (err) {
          if (!abortControllerRef.current?.signal.aborted) {
            setError(err instanceof Error ? err : new Error(String(err)));
          }
        } finally {
          if (abortControllerRef.current?.signal.aborted) {
            abort();
          }
        }
      } catch (err) {
        if (!abortControllerRef.current?.signal.aborted) {
          setError(err instanceof Error ? err : new Error(String(err)));
        }
      } finally {
        setIsConnected(false);
        isSubscribedRef.current = false;
      }
    };

    runSubscription();
  }, [rpcClient, addEvent]);

  const unsubscribe = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    isSubscribedRef.current = false;
    setIsConnected(false);
  }, []);

  const getEventsByType = useCallback(
    (type: EventType): AgentEvent[] => {
      return events.filter((e) => e.type === type);
    },
    [events]
  );

  const latestEvent = events.length > 0 ? events[events.length - 1] : null;

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  return {
    events,
    isConnected,
    error,
    subscribe,
    unsubscribe,
    clearEvents,
    getEventsByType,
    latestEvent,
  };
}

// Helper function to categorize events for display
export function categorizeEvent(event: AgentEvent): {
  category: "tool" | "thought" | "agent" | "control" | "task" | "log";
  isEphemeral: boolean;
} {
  switch (event.type) {
    case "tool_call_start":
    case "tool_call_end":
      return { category: "tool", isEphemeral: true };
    case "agent_thought":
      return { category: "thought", isEphemeral: true };
    case "agent_start":
    case "agent_end":
    case "agent_error":
    case "agent_routed":
      return { category: "agent", isEphemeral: event.type !== "agent_end" };
    case "approval_required":
    case "approval_response":
    case "workflow_interrupted":
      return { category: "control", isEphemeral: false };
    case "task_created":
    case "task_expanded":
    case "task_status_changed":
    case "confidence_update":
    case "validation_result":
      return { category: "task", isEphemeral: true };
    case "execution_record":
    case "log_message":
    default:
      return { category: "log", isEphemeral: true };
  }
}
