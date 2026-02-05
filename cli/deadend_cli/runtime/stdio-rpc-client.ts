/**
 * @file stdio-rpc-client.ts
 * @description JSON-RPC 2.0 client that communicates with a Python backend over stdio.
 *
 * This module implements a bidirectional RPC client that:
 * 1. Spawns a Python subprocess running the RPC server
 * 2. Sends JSON-RPC requests via stdin
 * 3. Receives JSON-RPC responses via stdout
 * 4. Supports both single-response and streaming RPC methods
 */
/**
 *
 * This module implements a bidirectional RPC client that:
 * 1. Spawns a Python subprocess running the RPC server
 * 2. Sends JSON-RPC requests via stdin
 * 3. Receives JSON-RPC responses via stdout
 * 4. Supports both single-response and streaming RPC methods
 *
 * ## Architecture
 *
 * ```
 * ┌─────────────────┐      stdin (JSON-RPC requests)      ┌─────────────────┐
 * │                 │ ──────────────────────────────────► │                 │
 * │  StdioRpcClient │                                     │  Python Server  │
 * │  (Deno/TS)      │ ◄────────────────────────────────── │  (RPC Server)   │
 * │                 │      stdout (JSON-RPC responses)    │                 │
 * └─────────────────┘                                     └─────────────────┘
 * ```
 *
 * ## Usage
 *
 * ```typescript
 * // Create and start the client
 * const client = new StdioRpcClient({
 *   pythonCommand: "uv",
 *   commandArgs: ["run", "python", "-m", "deadend_cli.jsonrpc_server"],
 * });
 * await client.start();
 *
 * // Make a single RPC call
 * const result = await client.call("ping");
 *
 * // Make a streaming RPC call
 * for await (const event of client.callStream("run_task", { target: "http://..." })) {
 *   console.log(event);
 * }
 *
 * // Clean up
 * client.close();
 * ```
 *
 * ## JSON-RPC 2.0 Protocol
 *
 * Request format:
 * ```json
 * {"jsonrpc": "2.0", "id": 1, "method": "methodName", "params": {...}}
 * ```
 *
 * Response format:
 * ```json
 * {"jsonrpc": "2.0", "id": 1, "result": {...}}
 * ```
 *
 * Error format:
 * ```json
 * {"jsonrpc": "2.0", "id": 1, "error": {"code": -32600, "message": "..."}}
 * ```
 */
import { logger } from "./logger.ts";

import type {
  JsonRpcRequest,
  JsonRpcResponse,
  JsonRpcError,
  StreamingRpcClient,
  PingResponse,
} from "../types/rpc.ts";

/**
 * Represents a pending single-response RPC request.
 */
interface SinglePendingRequest {
  type: "single";
  resolve: (value: unknown) => void;
  reject: (error: JsonRpcError) => void;
}

/**
 * Represents a pending streaming RPC request.
 */
interface StreamingPendingRequest {
  type: "streaming";
  controller: ReadableStreamDefaultController<unknown>;
  aborted: boolean;
}

/**
 * Union type for pending requests.
 */
type PendingRequest = SinglePendingRequest | StreamingPendingRequest;

/**
 * Custom error for RPC timeouts.
 */
class RpcTimeoutError extends Error {
  constructor(public method: string, public timeout: number) {
    super(`RPC call to ${method} timed out after ${timeout}ms`);
    this.name = "RpcTimeoutError";
  }
}

/**
 * Configuration options for the StdioRpcClient.
 *
 * @property pythonCommand - The Python executable to use (default: "python")
 *                           Can be "python", "python3", "uv", etc.
 * @property serverScript - The Python module to run (default: "deadend_cli.jsonrpc_server")
 *                          Used with "-m" flag unless commandArgs is provided
 * @property commandArgs - Custom command arguments that override the default "-m serverScript"
 *                         Example: ["run", "python", "-m", "module"] for uv
 * @property llmProvider - LLM provider to pass to the server via env var (default: "openai")
 * @property cwd - Working directory for the Python subprocess
 * @property env - Additional environment variables to pass to the subprocess
 * @property logFile - Optional path to file where stderr output will be written
 *                     If not provided, stderr is logged via logger
 */
export interface StdioRpcClientOptions {
  pythonCommand?: string;
  serverScript?: string;
  /** Custom command arguments. If provided, overrides the default "-m serverScript" args */
  commandArgs?: string[];
  llmProvider?: string;
  cwd?: string;
  env?: Record<string, string>;
  /** Optional path to file where stderr output will be written */
  logFile?: string;
}

/**
 * JSON-RPC 2.0 client that communicates with a Python backend over stdio.
 *
 * This client spawns a Python subprocess and communicates via stdin/stdout.
 * It supports both single-response RPC calls and streaming methods that
 * yield multiple responses.
 *
 * ## Lifecycle
 *
 * 1. **Construction**: Configure options (Python command, working dir, etc.)
 * 2. **start()**: Spawn the Python subprocess and begin reading stdout/stderr
 * 3. **call()/callStream()**: Make RPC requests and receive responses
 * 4. **close()**: Terminate the subprocess and clean up resources
 *
 * ## Error Handling
 *
 * - RPC errors are returned as JsonRpcError objects with code and message
 * - Network/process errors throw JavaScript Error objects
 * - Pending requests are rejected when the client is closed
 *
 * @implements {StreamingRpcClient}
 */
export class StdioRpcClient implements StreamingRpcClient {
  /** The spawned Python subprocess handle */
  private process: Deno.ChildProcess | null = null;

  /** Writer for sending data to the subprocess stdin */
  private stdin: WritableStreamDefaultWriter<Uint8Array> | null = null;

  /** Auto-incrementing request ID for JSON-RPC correlation */
  private requestId = 0;

  /** Map of pending requests awaiting responses, keyed by request ID */
  private pendingRequests = new Map<number, PendingRequest>();

  /** Text encoder for converting strings to bytes for stdin */
  private encoder = new TextEncoder();

  /** Text decoder for converting bytes from stdout to strings */
  private decoder = new TextDecoder();

  /** Buffer for accumulating partial lines from stdout */
  private buffer = "";

  /** File writer for stderr log file (if logFile option is provided) */
  private logFileWriter: Deno.FsFile | null = null;

  /** Flag indicating whether the client is running */
  private isRunning = false;

  /** Resolved configuration options with defaults applied */
  private options: Omit<Required<StdioRpcClientOptions>, 'commandArgs' | 'logFile'> & { commandArgs?: string[]; logFile?: string };

  /**
   * Creates a new StdioRpcClient with the specified options.
   *
   * @param options - Configuration options for the client
   *
   * @example
   * ```typescript
   * // Using default Python
   * const client = new StdioRpcClient();
   *
   * // Using uv to run the server
   * const client = new StdioRpcClient({
   *   pythonCommand: "uv",
   *   commandArgs: ["run", "python", "-m", "deadend_cli.jsonrpc_server"],
   *   cwd: "/path/to/project",
   * });
   * ```
   */
  constructor(options: StdioRpcClientOptions = {}) {
    this.options = {
      pythonCommand: options.pythonCommand ?? "python",
      serverScript: options.serverScript ?? "deadend_cli.jsonrpc_server",
      commandArgs: options.commandArgs ?? undefined,
      llmProvider: options.llmProvider ?? "openai",
      cwd: options.cwd ?? Deno.cwd(),
      env: options.env ?? {},
      logFile: options.logFile ?? undefined,
    };
  }

  /**
   * Starts the RPC client by spawning the Python subprocess.
   *
   * This method:
   * 1. Constructs the command with appropriate arguments
   * 2. Spawns the subprocess with piped stdin/stdout/stderr
   * 3. Begins reading stdout for JSON-RPC responses
   * 4. Begins reading stderr for logging/debugging
   *
   * @returns Promise that resolves when the subprocess is started
   *
   * @example
   * ```typescript
   * const client = new StdioRpcClient();
   * await client.start();
   * // Client is now ready to make RPC calls
   * ```
   */
  async start(): Promise<void> {
    if (this.isRunning) {
      return;
    }

    // Use custom commandArgs if provided, otherwise default to "-m serverScript"
    // This allows flexibility for different Python environments (venv, uv, poetry, etc.)
    const args = this.options.commandArgs ?? ["-m", this.options.serverScript];

    const command = new Deno.Command(this.options.pythonCommand, {
      args,
      stdin: "piped",   // write JSON-RPC requests
      stdout: "piped",  // read JSON-RPC responses
      stderr: "piped",  // read error/debug logs
      cwd: this.options.cwd,
      env: {
        ...Deno.env.toObject(),    // Inherit current environment
        ...this.options.env,        // Apply custom env vars
        LLM_PROVIDER: this.options.llmProvider,  // Tell server which LLM to use
      },
    });

    this.process = command.spawn();
    // Check if process started successfully
    if (!this.process.stdin || !this.process.stdout || !this.process.stderr) {
      throw new Error("Failed to spawn RPC server process - stdin/stdout/stderr not available");
    }
    
    this.stdin = this.process.stdin.getWriter();
    this.isRunning = true;
    
    // Check process status after a brief moment
    setTimeout(async () => {
      try {
        const status = await this.process!.status;
        if (!status.success && status.code !== null) {
          logger.error(`[RPC Client] Server process exited with code ${status.code}`);
          this.isRunning = false;
        }
      } catch {
        // Process might still be running, which is fine
      }
    }, 500);

    // Open log file if logFile option is provided
    if (this.options.logFile) {
      try {
        // Ensure directory exists
        const logPath = this.options.logFile;
        const logDir = logPath.substring(0, logPath.lastIndexOf("/"));
        if (logDir) {
          await Deno.mkdir(logDir, { recursive: true });
        }
        // Open file in append mode
        this.logFileWriter = await Deno.open(logPath, {
          create: true,
          append: true,
          write: true,
        });
      } catch (error) {
        logger.error("[RPC Client] Failed to open log file:", error);
        // Continue without file logging
      }
    }

    // Start background tasks to continuously read from stdout and stderr
    // These run concurrently and handle incoming data asynchronously
    // Don't await these - they run in the background
    this.readStdout().catch((error) => {
      if (this.isRunning) {
        logger.error("[RPC Client] Fatal error reading stdout:", error);
      }
    });
    this.readStderr().catch((error) => {
      if (this.isRunning) {
        logger.error("[RPC Client] Fatal error reading stderr:", error);
      }
    });

    // Give the server a moment to initialize before accepting requests
    // This prevents race conditions where we send requests before the server is ready
    await new Promise((resolve) => setTimeout(resolve, 100));
  }

  /**
   * Continuously reads from the subprocess stdout and processes JSON-RPC responses.
   *
   * This method runs in the background and:
   * 1. Reads chunks of data from stdout
   * 2. Decodes them as UTF-8 text
   * 3. Buffers partial lines (JSON-RPC uses newline-delimited JSON)
   * 4. Parses complete lines as JSON-RPC responses
   *
   * @private
   */
  private async readStdout(): Promise<void> {
    if (!this.process) return;

    const reader = this.process.stdout.getReader();

    try {
      while (this.isRunning) {
        const { done, value } = await reader.read();
        if (done) break;

        // Append decoded chunk to buffer, handling streaming decode
        this.buffer += this.decoder.decode(value, { stream: true });
        this.processBuffer();
      }
    } catch (error) {
      if (this.isRunning) {
        logger.error("[RPC Client] Error reading stdout:", error);
      }
    } finally {
      reader.releaseLock();
    }
  }

  /**
   * Continuously reads from the subprocess stderr and writes to log file or logs output.
   *
   * Stderr is used for:
   * - Python tracebacks and errors
   * - Debug logging from the server
   * - Rich console output (redirected to stderr to avoid polluting JSON-RPC)
   *
   * If logFile option is provided, output is written to the file.
   * Otherwise, it's logged via logger.
   *
   * @private
   */
  private async readStderr(): Promise<void> {
    if (!this.process) return;

    const reader = this.process.stderr.getReader();
    const encoder = new TextEncoder();

    try {
      while (this.isRunning) {
        const { done, value } = await reader.read();
        if (done) break;

        const text = this.decoder.decode(value, { stream: true });
        if (text.trim()) {
          if (this.logFileWriter) {
            // Write to log file
            try {
              await this.logFileWriter.write(encoder.encode(text));
              // Note: Deno.FsFile doesn't have flush(), writes are buffered
            } catch (error) {
              logger.error("[RPC Client] Failed to write to log file:", error);
            }
          } else {
            // Fallback to logger if no file is configured
            logger.error("[RPC Server]", text.trim());
          }
        }
      }
    } catch {
      // Ignore stderr read errors (common during shutdown)
    } finally {
      reader.releaseLock();
    }
  }

  /**
   * Processes the accumulated buffer, extracting and handling complete JSON lines.
   *
   * JSON-RPC over stdio uses newline-delimited JSON (NDJSON):
   * - Each JSON-RPC message is a single line
   * - Lines are separated by newline characters
   * - Partial lines are buffered until complete
   *
   * @private
   */
  private processBuffer(): void {
    const lines = this.buffer.split("\n");
    // Keep the last (potentially incomplete) line in the buffer
    this.buffer = lines.pop() ?? "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;

      try {
        const response: JsonRpcResponse = JSON.parse(trimmed);
        this.handleResponse(response);
      } catch (error) {
        // Failed to parse as JSON - likely a stray server log or non-JSON output
        // Log and skip this line
        logger.error("[RPC Client] Failed to parse JSON-RPC response:", trimmed, error);
      }
    }
  }

  /**
   * Handles a parsed JSON-RPC response by resolving the corresponding pending request.
   *
   * For single-response requests:
   * - Resolves the promise with the result, or rejects with the error
   *
   * For streaming requests:
   * - Enqueues each result to the stream controller
   * - Closes the stream when _streaming: false or _end: true is received
   *
   * @param response - The parsed JSON-RPC response
   * @private
   */
  private handleResponse(response: JsonRpcResponse): void {
    const id = response.id as number;
    const pending = this.pendingRequests.get(id);

    if (!pending) {
      logger.warn("[RPC Client] Received response for unknown request:", id);
      return;
    }

    // Handle error responses
    if (response.error) {
      this.handleError(id, pending, response.error);
      return;
    }

    if (pending.type === "streaming") {
      this.handleStreamingResponse(id, pending, response);
    } else {
      // Single response - resolve and clean up
      pending.resolve(response.result);
      this.pendingRequests.delete(id);
    }
  }

  /**
   * Handles errors for pending requests.
   */
  private handleError(
    id: number,
    pending: PendingRequest,
    error: JsonRpcError
  ): void {
    if (pending.type === "streaming") {
      pending.controller.error(error);
    } else {
      pending.reject(error);
    }
    this.pendingRequests.delete(id);
  }

  /**
   * Handles streaming responses with _streaming flags.
   */
  private handleStreamingResponse(
    id: number,
    pending: StreamingPendingRequest,
    response: JsonRpcResponse
  ): void {
    if (pending.aborted) {
      return;
    }

    const result = response.result as { _end?: boolean } | undefined;
    const isStreaming = (response as { _streaming?: boolean })._streaming;

    // Check for stream end signals
    if (result?._end === true || isStreaming === false) {
      // Don't enqueue the termination signal, just close
      pending.controller.close();
      this.pendingRequests.delete(id);
      return;
    }

    // Enqueue the result (intermediate streaming result)
    pending.controller.enqueue(result);
  }

  /**
   * Sends a JSON-RPC request to the subprocess via stdin.
   *
   * @param request - The JSON-RPC request object to send
   * @throws {Error} If the client is not running
   * @private
   */
  private async sendRequest(request: JsonRpcRequest): Promise<void> {
    if (!this.stdin || !this.isRunning) {
      throw new Error("RPC client is not running");
    }

    // Serialize as JSON with newline delimiter
    const data = JSON.stringify(request) + "\n";
    logger.log("[RPC Client] Sending request:", request.method, "id:", request.id);
    await this.stdin.write(this.encoder.encode(data));
    // Ensure the data is flushed to the subprocess
    await this.stdin.ready;
  }

  /**
   * Makes a single-response RPC call.
   *
   * @param method - The RPC method name to call
   * @param params - Optional parameters to pass to the method
   * @param timeout - Timeout in milliseconds (default: 30000)
   * @returns Promise resolving to the method result
   * @throws {RpcTimeoutError} If the call times out
   * @throws {JsonRpcError} If the RPC call returns an error
   */
  async call<T>(method: string, params?: unknown, timeout = 30000): Promise<T> {
    if (!this.isRunning) {
      await this.start();
    }

    const id = ++this.requestId;
    const request: JsonRpcRequest = {
      jsonrpc: "2.0",
      id,
      method,
      params,
    };

    return new Promise((resolve, reject) => {
      const timeoutId = setTimeout(() => {
        this.pendingRequests.delete(id);
        reject(new RpcTimeoutError(method, timeout));
      }, timeout);

      this.pendingRequests.set(id, {
        type: "single",
        resolve: (value) => {
          clearTimeout(timeoutId);
          resolve(value as T);
        },
        reject: (error) => {
          clearTimeout(timeoutId);
          reject(error);
        },
      });

      this.sendRequest(request).catch((error) => {
        clearTimeout(timeoutId);
        this.pendingRequests.delete(id);
        reject(error);
      });
    });
  }

  /**
   * Make a streaming RPC call.
   *
   * The stream ends when:
   * 1. Server sends { _streaming: false } in response
   * 2. Server sends { _end: true } in result
   * 3. Server sends an error response
   * 4. Client calls abort on the returned controller
   *
   * @param method - The RPC method name to call
   * @param params - Optional parameters to pass to the method
   * @returns Object with generator and abort function
   */
  stream<T>(
    method: string,
    params?: unknown
  ): { generator: AsyncGenerator<T>; abort: () => void } {
    if (!this.isRunning) {
      // Start asynchronously, but don't wait
      this.start().catch((error) => {
        logger.error("[RPC Client] Failed to start client:", error);
      });
    }

    const id = ++this.requestId;
    const abortController = new AbortController();

    const stream = new ReadableStream<T>({
      start: (controller) => {
        this.pendingRequests.set(id, {
          type: "streaming",
          controller,
          aborted: false,
        });

        this.sendRequest({ jsonrpc: "2.0", id, method, params }).catch((error) => {
          controller.error(error);
          this.pendingRequests.delete(id);
        });
      },
      cancel: () => {
        const pending = this.pendingRequests.get(id);
        if (pending?.type === "streaming") {
          pending.aborted = true;
          // Send cancellation to server
          this.sendRequest({
            jsonrpc: "2.0",
            id: null,
            method: "cancel",
            params: { id },
          }).catch(() => {
            // Ignore errors when sending cancellation
          });
        }
        this.pendingRequests.delete(id);
      },
    });

    const generator = async function* () {
    const reader = stream.getReader();
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        yield value;
      }
    } finally {
      reader.releaseLock();
    }
    }();

    return {
      generator,
      abort: () => abortController.abort(),
    };
  }

  /**
   * Makes a streaming RPC call and yields results as they arrive.
   *
   * @deprecated Use stream() instead for better control
   * @param method - The RPC method name to call
   * @param params - Optional parameters to pass to the method
   * @yields Each event/result from the streaming method
   */
  async *callStream(method: string, params?: unknown): AsyncGenerator<unknown, void, unknown> {
    const { generator } = this.stream(method, params);
    yield* generator;
  }

  /**
   * Sends a JSON-RPC notification (a request with no response expected).
   *
   * Notifications are fire-and-forget messages. The server processes them
   * but does not send a response. Use for events/signals that don't need
   * acknowledgment.
   *
   * @param method - The RPC method name to call
   * @param params - Optional parameters to pass to the method
   *
   * @example
   * ```typescript
   * // Send a cancel signal
   * client.notify("cancel_task", { task_id: "123" });
   * ```
   */
  notify(method: string, params?: unknown): void {
    if (!this.isRunning) {
      logger.warn("[RPC Client] Cannot send notification: client not running");
      return;
    }

    // Notifications have null id (no response expected)
    const request: JsonRpcRequest = {
      jsonrpc: "2.0",
      id: null,
      method,
      params,
    };

    this.sendRequest(request).catch((error) => {
      logger.error("[RPC Client] Failed to send notification:", error);
    });
  }

  /**
   * Sends a ping request to verify the server is responsive.
   *
   * @returns Promise resolving to true if server responds, false otherwise
   *
   * @example
   * ```typescript
   * const isAlive = await client.ping();
   * if (!isAlive) {
   *   console.error("Server is not responding");
   * }
   * ```
   */
  async ping(): Promise<boolean> {
    try {
      const result = await this.call("ping") as PingResponse;
      return result?.status === "ok";
    } catch {
      return false;
    }
  }

  /**
   * Closes the RPC client and terminates the subprocess.
   *
   * This method:
   * 1. Rejects all pending requests with a "Client closed" error
   * 2. Closes the stdin writer
   * 3. Sends SIGTERM to the subprocess
   *
   * After calling close(), the client cannot be reused. Create a new
   * instance if you need to reconnect.
   *
   * @example
   * ```typescript
   * // Clean shutdown
   * client.close();
   * ```
   */
  close(): void {
    this.isRunning = false;

    // Reject all pending requests so callers don't hang forever
    for (const [id, pending] of this.pendingRequests) {
      if (pending.type === "streaming") {
        pending.controller.error(new Error("Client closed"));
      } else {
        pending.reject({
          code: -32000,
          message: "Client closed",
        });
      }
      this.pendingRequests.delete(id);
    }

    // Close stdin to signal EOF to the subprocess
    if (this.stdin) {
      try {
        this.stdin.close();
      } catch {
        // Ignore close errors (may already be closed)
      }
      this.stdin = null;
    }

    // Terminate the subprocess gracefully
    if (this.process) {
      try {
        this.process.kill("SIGTERM");
      } catch {
        // Ignore kill errors (may already be dead)
      }
      this.process = null;
    }
  }

  /**
   * Returns whether the client is currently running.
   *
   * @returns true if the client is running and can make RPC calls
   */
  get running(): boolean {
    return this.isRunning;
  }
}

/**
 * Convenience function to create and start an RPC client in one step.
 *
 * @param options - Configuration options for the client
 * @returns Promise resolving to a started StdioRpcClient
 *
 * @example
 * ```typescript
 * const client = await createStdioRpcClient({
 *   pythonCommand: "python3",
 * });
 * // Client is ready to use
 * ```
 */
export async function createStdioRpcClient(
  options?: StdioRpcClientOptions
): Promise<StdioRpcClient> {
  const client = new StdioRpcClient(options);
  await client.start();
  return client;
}
