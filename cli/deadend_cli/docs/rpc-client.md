# RPC Client Implementation Summary

## Overview

Created a TypeScript/Deno RPC client that communicates with the Python `RPCServer` via JSON-RPC 2.0 over stdio (stdin/stdout). The implementation supports both single-response calls and streaming responses for long-running tasks.

## Files Created/Modified

| File | Description |
|------|-------------|
| `lib/stdio-rpc-client.ts` | Low-level stdio JSON-RPC client |
| `lib/deadend-rpc-client.ts` | High-level DeadEnd-specific wrapper |
| `types/rpc.ts` | Extended with streaming types |
| `lib/rpc-client.ts` | Re-exports for convenience |

---

## Architecture

```
┌─────────────────────┐         stdin (JSON-RPC requests)
│   Deno CLI App      │ ────────────────────────────────────►┌─────────────────────┐
│                     │                                       │  Python RPCServer   │
│  DeadEndRpcClient   │ ◄────────────────────────────────────│                     │
│         │           │         stdout (JSON-RPC responses)   │  - ping             │
│  StdioRpcClient     │                                       │  - run_task         │
└─────────────────────┘                                       └─────────────────────┘
```

---

## StdioRpcClient

**File:** `lib/stdio-rpc-client.ts`

**Purpose:** Low-level JSON-RPC 2.0 client that spawns and communicates with the Python server.

### Key Features

- Spawns Python server as a child process
- Multiplexes multiple concurrent requests by ID
- Handles line-buffered JSON responses
- Supports streaming (multiple responses per request)

### Interface

```typescript
class StdioRpcClient implements StreamingRpcClient {
  start(): Promise<void>           // Spawn server process
  call(method, params): Promise    // Single response call
  callStream(method, params): AsyncGenerator  // Streaming call
  notify(method, params): void     // Fire-and-forget
  ping(): Promise<boolean>         // Health check
  close(): void                    // Cleanup
}
```

### Options

```typescript
interface StdioRpcClientOptions {
  pythonCommand?: string;    // Default: "python"
  serverScript?: string;     // Default: "deadend_cli.rpc_server"
  llmProvider?: string;      // Default: "openai"
  cwd?: string;              // Working directory
  env?: Record<string, string>;  // Additional env vars
}
```

---

## DeadEndRpcClient

**File:** `lib/deadend-rpc-client.ts`

**Purpose:** High-level wrapper with typed DeadEnd-specific methods.

### Key Features

- Typed task events (`ReconEvent`, `ExploitEvent`, `DoneEvent`)
- Optional callbacks for event handling
- Async generator for streaming task results

### Interface

```typescript
class DeadEndRpcClient {
  start(): Promise<void>
  ping(): Promise<boolean>
  runTask(params): AsyncGenerator<DeadEndTaskEvent>
  runTaskWithCallbacks(params): Promise<DoneEvent>
  close(): void
}
```

### Event Types

```typescript
type DeadEndTaskEvent = ReconEvent | ExploitEvent | DoneEvent;

interface ReconEvent   { phase: "recon";   data: unknown }
interface ExploitEvent { phase: "exploit"; data: unknown }
interface DoneEvent    { phase: "done";    mode: string; target: string; ... }
```

---

## Type Definitions

**File:** `types/rpc.ts`

### New Additions

```typescript
interface StreamingRpcClient extends RpcClient {
  callStream(method, params): AsyncGenerator<unknown>
  ping(): Promise<boolean>
  close(): void
}

interface RunTaskParams {
  prompt: string;
  target: string;
  openapi_spec?: unknown;
  knowledge_base?: string;
  mode?: "yolo" | "safe";
}

type TaskPhase = "recon" | "exploit" | "done";
```

---

## Protocol Compatibility

| Python Server Method | Client Method | Response Type |
|---------------------|---------------|---------------|
| `ping` | `client.ping()` | Single: `{ status: "ok" }` |
| `run_task` | `client.runTask(params)` | Streaming: multiple `TaskEvent` |

### JSON-RPC 2.0 Message Format

```json
// Request
{"jsonrpc": "2.0", "id": 1, "method": "run_task", "params": {...}}

// Response (repeated for streaming)
{"jsonrpc": "2.0", "id": 1, "result": {"phase": "recon", "data": ...}}
{"jsonrpc": "2.0", "id": 1, "result": {"phase": "exploit", "data": ...}}
{"jsonrpc": "2.0", "id": 1, "result": {"phase": "done", ...}}
```

---

## Usage Examples

### Basic Streaming

```typescript
import { createDeadEndRpcClient } from "./lib/rpc-client.ts";

const client = await createDeadEndRpcClient();

for await (const event of client.runTask({
  prompt: "Find vulnerabilities",
  target: "http://example.com",
})) {
  console.log(`[${event.phase}]`, event.phase === "done" ? "Complete" : event.data);
}

client.close();
```

### With Callbacks

```typescript
const client = await createDeadEndRpcClient({
  onRecon: (data) => console.log("Recon:", data),
  onExploit: (data) => console.log("Exploit:", data),
  onDone: (event) => console.log("Done:", event.target),
  onError: (err) => console.error("Error:", err),
});

await client.runTaskWithCallbacks({
  prompt: "Test for SQL injection",
  target: "http://vulnerable-app.com",
  mode: "safe",
});
```

### Low-Level Access

```typescript
import { createStdioRpcClient } from "./lib/rpc-client.ts";

const client = await createStdioRpcClient();
const isAlive = await client.ping();
console.log("Server alive:", isAlive);
```

---

## Error Handling

The client handles errors at multiple levels:

1. **Connection errors** - Thrown when the server process fails to start
2. **JSON-RPC errors** - Returned as `JsonRpcError` objects with code and message
3. **Stream errors** - Propagated through the async generator

```typescript
try {
  for await (const event of client.runTask(params)) {
    // Handle events
  }
} catch (error) {
  if ('code' in error) {
    // JSON-RPC error
    console.error(`RPC Error ${error.code}: ${error.message}`);
  } else {
    // Other error
    console.error(error);
  }
}
```

---

## Cleanup

Always call `close()` when done to properly terminate the server process:

```typescript
const client = await createDeadEndRpcClient();

try {
  // Use client...
} finally {
  client.close();
}
```
