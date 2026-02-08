#!/bin/bash
# Post-build script to fix executable permissions for Playwright and other binaries
# This should be run after building with PyOxidizer

INSTALL_DIR="${1:-build/x86_64-unknown-linux-gnu/debug/install}"

if [ ! -d "$INSTALL_DIR" ]; then
    echo "Error: Install directory not found: $INSTALL_DIR"
    exit 1
fi

echo "Fixing executable permissions in $INSTALL_DIR..."

# Fix Playwright driver node binary
if [ -f "$INSTALL_DIR/lib/playwright/driver/node" ]; then
    chmod +x "$INSTALL_DIR/lib/playwright/driver/node"
    echo "Fixed: playwright/driver/node"
fi

# Fix all shell scripts in playwright
find "$INSTALL_DIR/lib/playwright" -type f \( -name "*.sh" -o -name "playwright*" \) -exec chmod +x {} \; 2>/dev/null

# Fix browser executables in .local-browsers
BROWSER_PATH="$INSTALL_DIR/lib/playwright/driver/package/.local-browsers"
if [ -d "$BROWSER_PATH" ]; then
    echo "Fixing permissions for Playwright browsers..."
    find "$BROWSER_PATH" -type f \( -name "chrome-headless-shell" -o -name "chrome-headless-shell*" -o -name "chrome*" -o -name "chromium*" \) -exec chmod +x {} \; 2>/dev/null || true
    # Also fix permissions in subdirectories
    find "$BROWSER_PATH" -type d -name "*chrome*" -exec find {} -type f -exec chmod +x {} \; \; 2>/dev/null || true
fi

# Fix any other executables that might need it
find "$INSTALL_DIR/lib" -type f \( -name "node" -o -name "*.so" \) -exec chmod +x {} \; 2>/dev/null

echo "Permissions fixed!"
