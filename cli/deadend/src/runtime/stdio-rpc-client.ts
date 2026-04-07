import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { appendFile } from "node:fs/promises";
import type {
  JsonRpcError,
  JsonRpcRequest,
  JsonRpcResponse,
  PingResponse,
} from "./rpc-types.ts";

interface StdioRpcClientOptions {
  pythonCommand: string;
  commandArgs: string[];
  cwd: string;
  env: Record<string, string>;
  logFile?: string;
}

interface StreamingPendingRequest {
  type: "streaming";
  controller: ReadableStreamDefaultController<unknown>;
  aborted: boolean;
}

interface SinglePendingRequest {
  type: "single";
  resolve: (value: unknown) => void;
  reject: (error: JsonRpcError | Error) => void;
}

type PendingRequest = StreamingPendingRequest | SinglePendingRequest;
type RpcProcess = ChildProcessWithoutNullStreams;

class RpcTimeoutError extends Error {
  constructor(method: string, timeout: number) {
    super(`RPC call to ${method} timed out after ${timeout}ms`);
  }
}

export class StdioRpcClient {
  private process: RpcProcess | null = null;
  private requestId = 0;
  private pendingRequests = new Map<number, PendingRequest>();
  private buffer = "";
  private isRunning = false;
  private exitWaiters: Array<() => void> = [];

  constructor(private readonly options: StdioRpcClientOptions) {}

  async start(): Promise<void> {
    if (this.isRunning) {
      return;
    }

    this.process = spawn(this.options.pythonCommand, this.options.commandArgs, {
      cwd: this.options.cwd,
      env: this.options.env,
      stdio: "pipe",
    });

    this.isRunning = true;
    this.process.stdout.setEncoding("utf8");
    this.process.stderr.setEncoding("utf8");
    this.process.stdout.on("data", (chunk: string) => {
      this.buffer += chunk;
      this.processBuffer();
    });
    this.process.stderr.on("data", (chunk: string) => {
      void this.handleStderr(chunk);
    });
    this.process.on("exit", (code) => {
      this.handleProcessExit(code);
    });
    this.process.on("error", (error) => {
      this.handleProcessError(error);
    });

    await new Promise((resolve) => setTimeout(resolve, 100));

    if (this.process.exitCode !== null && this.process.exitCode !== 0) {
      throw new Error(`RPC server exited with code ${this.process.exitCode}`);
    }
  }

  async call<T>(method: string, params?: unknown, timeout = 30_000): Promise<T> {
    if (!this.isRunning) {
      await this.start();
    }

    const id = ++this.requestId;

    return await new Promise<T>((resolve, reject) => {
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

      void this.sendRequest({
        jsonrpc: "2.0",
        id,
        method,
        params,
      }).catch((error) => {
        clearTimeout(timeoutId);
        this.pendingRequests.delete(id);
        reject(error);
      });
    });
  }

  stream<T>(
    method: string,
    params?: unknown,
  ): { generator: AsyncGenerator<T>; abort: () => void } {
    const id = ++this.requestId;
    let readableStream: ReadableStream<T> | null = null;

    readableStream = new ReadableStream<T>({
      start: (controller) => {
        this.pendingRequests.set(id, {
          type: "streaming",
          controller,
          aborted: false,
        });

        void this.sendRequest({
          jsonrpc: "2.0",
          id,
          method,
          params,
        }).catch((error) => {
          controller.error(error);
          this.pendingRequests.delete(id);
        });
      },
      cancel: async () => {
        this.abortStream(id);
      },
    });

    const generator = async function* () {
      const reader = readableStream!.getReader();

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) {
            break;
          }

          yield value;
        }
      } finally {
        reader.releaseLock();
      }
    }();

    return {
      generator,
      abort: () => {
        this.abortStream(id);
      },
    };
  }

  notify(method: string, params?: unknown): void {
    if (!this.isRunning) {
      return;
    }

    void this.sendRequest({
      jsonrpc: "2.0",
      id: null,
      method,
      params,
    });
  }

  async ping(): Promise<boolean> {
    try {
      const result = await this.call<PingResponse>("ping");
      return result.status === "ok";
    } catch {
      return false;
    }
  }

  async shutdown(timeout = 5_000): Promise<void> {
    if (!this.isRunning) {
      return;
    }

    const gracefulDeadline = Math.max(1_000, Math.min(timeout, 3_000));
    try {
      await this.call("shutdown", undefined, gracefulDeadline);
    } catch {
      // Fall through to process-exit waiting and forced termination.
    }

    const exitedGracefully = await this.waitForProcessExit(Math.max(250, timeout - gracefulDeadline));
    if (exitedGracefully) {
      return;
    }

    this.terminateProcess("SIGTERM");
    const exitedAfterTerm = await this.waitForProcessExit(1_500);
    if (exitedAfterTerm) {
      return;
    }

    this.terminateProcess("SIGKILL");
    await this.waitForProcessExit(500);
  }

  close(): void {
    this.isRunning = false;

    for (const [id, pending] of this.pendingRequests) {
      try {
        if (pending.type === "streaming") {
          pending.controller.error(new Error("Client closed"));
        } else {
          pending.reject(new Error("Client closed"));
        }
      } catch {
        // Stream may already be closed/errored during shutdown.
      }
      this.pendingRequests.delete(id);
    }

    try {
      this.process?.stdin.end();
    } catch {
      // Ignore stdin close failures during shutdown.
    }

    try {
      this.process?.kill("SIGTERM");
    } catch {
      // Ignore kill failures during shutdown.
    }

    this.process = null;
  }

  get running(): boolean {
    return this.isRunning;
  }

  private async sendRequest(request: JsonRpcRequest): Promise<void> {
    if (!this.process?.stdin || !this.isRunning) {
      throw new Error("RPC client is not running");
    }

    await new Promise<void>((resolve, reject) => {
      this.process!.stdin.write(`${JSON.stringify(request)}\n`, "utf8", (error) => {
        if (error) {
          reject(error);
          return;
        }

        resolve();
      });
    });
  }

  private async handleStderr(chunk: string): Promise<void> {
    if (!this.options.logFile) {
      return;
    }

    await appendFile(this.options.logFile, chunk);
  }

  private processBuffer(): void {
    const lines = this.buffer.split("\n");
    this.buffer = lines.pop() ?? "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) {
        continue;
      }

      try {
        const response = JSON.parse(trimmed) as JsonRpcResponse;
        this.handleResponse(response);
      } catch {
        // Ignore non-JSON lines from the backend.
      }
    }
  }

  private handleResponse(response: JsonRpcResponse): void {
    const id = response.id ?? -1;
    const pending = this.pendingRequests.get(id);

    if (!pending) {
      return;
    }

    if (response.error) {
      if (pending.type === "streaming") {
        pending.controller.error(response.error);
      } else {
        pending.reject(response.error);
      }
      this.pendingRequests.delete(id);
      return;
    }

    if (pending.type === "streaming") {
      const result = response.result as { _end?: boolean } | undefined;
      if (response._streaming === false || result?._end === true) {
        pending.controller.close();
        this.pendingRequests.delete(id);
        return;
      }

      pending.controller.enqueue(response.result);
      return;
    }

    pending.resolve(response.result);
    this.pendingRequests.delete(id);
  }

  private handleProcessExit(code: number | null): void {
    if (!this.isRunning) {
      this.resolveExitWaiters();
      return;
    }

    const error = new Error(`RPC server exited with code ${code ?? "unknown"}`);
    this.failPendingRequests(error);
    this.isRunning = false;
    this.process = null;
    this.resolveExitWaiters();
  }

  private handleProcessError(error: Error): void {
    this.failPendingRequests(error);
    this.isRunning = false;
    this.process = null;
    this.resolveExitWaiters();
  }

  private failPendingRequests(error: Error): void {
    for (const [id, pending] of this.pendingRequests) {
      try {
        if (pending.type === "streaming") {
          pending.controller.error(error);
        } else {
          pending.reject(error);
        }
      } catch {
        // Stream may already be closed/errored.
      }
      this.pendingRequests.delete(id);
    }
  }

  private abortStream(id: number): void {
    const pending = this.pendingRequests.get(id);
    if (!pending || pending.type !== "streaming") {
      return;
    }

    pending.aborted = true;
    try {
      pending.controller.close();
    } catch {
      // Controller may already be closed.
    }
    this.pendingRequests.delete(id);
    void this.sendRequest({
      jsonrpc: "2.0",
      id: null,
      method: "cancel",
      params: { id },
    }).catch(() => {
      return;
    });
  }

  private waitForProcessExit(timeout: number): Promise<boolean> {
    if (!this.process || this.process.exitCode !== null || !this.isRunning) {
      return Promise.resolve(true);
    }

    return new Promise((resolve) => {
      const onExit = () => {
        clearTimeout(timeoutId);
        resolve(true);
      };

      const timeoutId = setTimeout(() => {
        this.exitWaiters = this.exitWaiters.filter((waiter) => waiter !== onExit);
        resolve(false);
      }, timeout);

      this.exitWaiters.push(onExit);
    });
  }

  private terminateProcess(signal: NodeJS.Signals): void {
    try {
      this.process?.stdin.end();
    } catch {
      // Ignore stdin close failures during shutdown.
    }

    try {
      this.process?.kill(signal);
    } catch {
      // Ignore kill failures during shutdown.
    }
  }

  private resolveExitWaiters(): void {
    const waiters = this.exitWaiters;
    this.exitWaiters = [];
    for (const waiter of waiters) {
      waiter();
    }
  }
}
