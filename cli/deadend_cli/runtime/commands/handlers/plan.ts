import { getCurrentTarget } from "./target.ts";

// Special token to signal Chat component to switch to NormalView
export const START_NORMAL_MODE = "START_NORMAL_MODE";

export interface NormalParams {
  target: string;
  task: string;
}

// Storage for normal mode params to be read by Chat component
let pendingNormalParams: NormalParams | null = null;

export function getPendingNormalParams(): NormalParams | null {
  const params = pendingNormalParams;
  pendingNormalParams = null; // Clear after reading
  return params;
}

export function handlePlan(args: string[]): string {
  // Check if target is set
  const target = getCurrentTarget();
  if (!target) {
    return `Error: No target set. Use /target <url> first.\n\nExample:\n  /target https://example.com\n  /plan Analyze the API for authentication issues`;
  }

  // Get the task from args or use default
  const task = args.length > 0
    ? args.join(" ")
    : "Plan a comprehensive security assessment with task decomposition";

  // Store params for the NormalView component
  pendingNormalParams = { target, task };

  // Return special token to trigger view switch
  return START_NORMAL_MODE;
}

