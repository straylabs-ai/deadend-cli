/**
 * @file BlinkDot.tsx
 * @description Animated status dot indicator.
 *
 * Renders a small circle that blinks on/off when `animate` is true
 * (for pending / running states) and stays solid when false
 * (for completed / error states).
 *
 * Inspired by Letta Code's BlinkDot component.
 */

import { useState, useEffect } from "react";
import { Text } from "ink";

export interface BlinkDotProps {
  /** Color of the dot (hex or named) */
  color: string;
  /** Whether the dot should blink */
  animate?: boolean;
  /** Symbol to display (default: "●") */
  symbol?: string;
}

export function BlinkDot({
  color,
  animate = false,
  symbol = "\u25CF", // ●
}: BlinkDotProps) {
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    if (!animate) {
      setVisible(true);
      return;
    }

    const id = setInterval(() => {
      setVisible((v) => !v);
    }, 400);

    return () => clearInterval(id);
  }, [animate]);

  return (
    <Text color={color}>{visible || !animate ? symbol : " "}</Text>
  );
}
