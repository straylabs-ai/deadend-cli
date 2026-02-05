import { getCurrentTarget } from "./target.ts";

// Special token to signal Chat component to switch to YoloView
export const START_YOLO_MODE = "START_YOLO_MODE";

export interface YoloParams {
  target: string;
  task: string;
}

// Storage for yolo params to be read by Chat component
let pendingYoloParams: YoloParams | null = null;

export function getPendingYoloParams(): YoloParams | null {
  const params = pendingYoloParams;
  pendingYoloParams = null; // Clear after reading
  return params;
}

export async function handleYolo(args: string[]): Promise<string> {
  // Check if target is set
  const target = getCurrentTarget();
  if (!target) {
    return `Error: No target set. Use /target <url> first.\n\nExample:\n  /target https://example.com\n  /yolo Look for SQL injection vulnerabilities`;
  }

  // Get the task from args or use default
  const task = args.length > 0
    ? args.join(" ")
    : "Perform a comprehensive security assessment, looking for common vulnerabilities";

  // Store params for the YoloView component
  pendingYoloParams = { target, task };

  // Return special token to trigger view switch
  return START_YOLO_MODE;
}

