import { useState, useEffect } from "react";
import { Text, Box } from "ink";

// Nested triangles animation
const triangleFrames = ["◸", "◹", "◿", "◺", "◸", "◹", "◿", "◺"];

// Animated bar
const barFrames = [
  "▰▱▱▱▱▱▱",
  "▰▰▱▱▱▱▱",
  "▰▰▰▱▱▱▱",
  "▰▰▰▰▱▱▱",
  "▰▰▰▰▰▱▱",
  "▰▰▰▰▰▰▱",
  "▰▰▰▰▰▰▰",
  "▱▰▰▰▰▰▰",
  "▱▱▰▰▰▰▰",
  "▱▱▱▰▰▰▰",
  "▱▱▱▱▰▰▰",
  "▱▱▱▱▱▰▰",
  "▱▱▱▱▱▱▰",
  "▱▱▱▱▱▱▱",
];

interface LoadingSpinnerProps {
  text?: string;
  color?: string;
}

export function LoadingSpinner({ text = "Thinking", color = "magenta" }: LoadingSpinnerProps) {
  const [triangleIndex, setTriangleIndex] = useState(0);
  const [barIndex, setBarIndex] = useState(0);

  useEffect(() => {
    const triangleInterval = setInterval(() => {
      setTriangleIndex((prev) => (prev + 1) % triangleFrames.length);
    }, 100);

    const barInterval = setInterval(() => {
      setBarIndex((prev) => (prev + 1) % barFrames.length);
    }, 120);

    return () => {
      clearInterval(triangleInterval);
      clearInterval(barInterval);
    };
  }, []);

  return (
    <Box flexDirection="row" gap={1}>
      <Text color={color} bold>{triangleFrames[triangleIndex]}</Text>
      <Text color={color} bold>{text}</Text>
      <Text color={color} dimColor>{barFrames[barIndex]}</Text>
    </Box>
  );
}

