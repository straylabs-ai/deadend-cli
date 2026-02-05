/**
 * @file logger.ts
 * @description Centralized logging utility with DEBUG flag support
 * 
 * All console logging should go through this utility to respect the DEBUG flag.
 * Errors are always logged regardless of DEBUG flag.
 */

// Debug flag - set to true to enable debug console logs
// Can also be controlled via environment variable: DEBUG=true
const DEBUG = Deno.env.get("DEBUG") === "true" || false;

/**
 * Logger utility that respects DEBUG flag
 */
export const logger = {
  /**
   * Log debug/info messages (only if DEBUG is true)
   */
  log: (...args: unknown[]) => {
    if (DEBUG) {
      console.log(...args);
    }
  },

  /**
   * Log warning messages (only if DEBUG is true)
   */
  warn: (...args: unknown[]) => {
    if (DEBUG) {
      console.warn(...args);
    }
  },

  /**
   * Log error messages (always logged, regardless of DEBUG flag)
   */
  error: (...args: unknown[]) => {
    console.error(...args);
  },

  /**
   * Log info messages (only if DEBUG is true)
   */
  info: (...args: unknown[]) => {
    if (DEBUG) {
      console.info(...args);
    }
  },

  /**
   * Log debug messages (only if DEBUG is true)
   */
  debug: (...args: unknown[]) => {
    if (DEBUG) {
      console.debug(...args);
    }
  },
};

/**
 * Export DEBUG flag for conditional logic if needed
 */
export { DEBUG };

