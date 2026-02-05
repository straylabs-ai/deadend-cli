let currentTarget: string | null = null;

/** Token returned to signal Chat to initialize agent for target */
export const TARGET_SET_PREFIX = "TARGET_SET:";

export function getCurrentTarget(): string | null {
  return currentTarget;
}

export function setTarget(target: string): void {
  currentTarget = target;
}

export async function handleTarget(args: string[]): Promise<string> {
  if (args.length === 0) {
    if (currentTarget) {
      return `Current target: ${currentTarget}`;
    }
    return `No target set. Usage: /target <url|hostname>`;
  }

  const target = args[0].trim();

  // Validate target format
  if (!isValidTarget(target)) {
    return `Error: Invalid target format. Please provide a valid URL (http://example.com) or hostname (example.com)`;
  }

  // Check reachability
  try {
    const isReachable = await checkReachability(target);

    if (isReachable) {
      currentTarget = target;
      // Return special token with target - Chat component will initialize agent
      return `${TARGET_SET_PREFIX}${target}`;
    } else {
      return `Error: Target ${target} is not reachable. Please check the URL/hostname and try again.`;
    }
  } catch (error) {
    return `Error checking target reachability: ${error instanceof Error ? error.message : "Unknown error"}`;
  }
}

function isValidTarget(target: string): boolean {
  // Check if it's a valid URL
  try {
    const url = new URL(target.startsWith("http") ? target : `https://${target}`);
    return url.hostname.length > 0;
  } catch {
    // If URL parsing fails, check if it's a valid hostname
    // Basic hostname validation: alphanumeric, dots, hyphens
    const hostnamePattern = /^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$/;
    return hostnamePattern.test(target);
  }
}

async function checkReachability(target: string): Promise<boolean> {
  try {
    // Normalize target to URL format
    let url: string;
    if (target.startsWith("http://") || target.startsWith("https://")) {
      url = target;
    } else {
      // Try HTTPS first, then HTTP
      url = `https://${target}`;
    }

    // Try to fetch with a timeout
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000); // 5 second timeout

    try {
      const response = await fetch(url, {
        method: "HEAD",
        signal: controller.signal,
        redirect: "follow",
      });
      clearTimeout(timeoutId);
      
      // Consider 2xx, 3xx, 4xx as reachable (server responded)
      // 5xx might be reachable but server error
      return response.status < 500;
    } catch (fetchError) {
      clearTimeout(timeoutId);
      
      // If HTTPS fails, try HTTP
      if (url.startsWith("https://")) {
        const httpUrl = url.replace("https://", "http://");
        try {
          const controller2 = new AbortController();
          const timeoutId2 = setTimeout(() => controller2.abort(), 5000);
          
          const response = await fetch(httpUrl, {
            method: "HEAD",
            signal: controller2.signal,
            redirect: "follow",
          });
          clearTimeout(timeoutId2);
          
          return response.status < 500;
        } catch {
          return false;
        }
      }
      
      return false;
    }
  } catch (error) {
    // If it's a network error or timeout, target is not reachable
    return false;
  }
}

