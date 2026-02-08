#!/bin/bash
# Install Playwright browsers to the build directory
# Usage: install_playwright_browsers.sh <build_dir>

set -e

if [ -z "$1" ]; then
    echo "Error: Build directory not provided"
    echo "Usage: $0 <build_dir>"
    exit 1
fi

BUILD_DIR="$1"

# The browser path should match what's in the built package
BROWSER_BASE_PATH="${BUILD_DIR}/lib/playwright/driver/package"
BROWSER_PATH="${BROWSER_BASE_PATH}/.local-browsers"
mkdir -p "$BROWSER_PATH"

# Detect if we're on macOS (which requires --break-system-packages)
PIP_FLAGS=""
IS_MACOS=false
if [[ "$(uname -s)" == "Darwin" ]]; then
    PIP_FLAGS="--break-system-packages"
    IS_MACOS=true
fi

# Install playwright to get the driver and browser installation script
# Skip pip upgrade on macOS as it's managed by Homebrew and can't be upgraded via pip
if [ "$IS_MACOS" = false ]; then
    python3 -m pip install --upgrade pip $PIP_FLAGS
fi
python3 -m pip install playwright $PIP_FLAGS

# First, install browsers to default location to get the version
python3 -m playwright install chromium

# Find the installed chromium version
PLAYWRIGHT_CACHE="${HOME}/.cache/ms-playwright"
CHROMIUM_DIR=$(find "$PLAYWRIGHT_CACHE" -maxdepth 1 -type d -name "chromium-*" 2>/dev/null | head -n 1)

if [ -z "$CHROMIUM_DIR" ]; then
    # Try alternative location (macOS)
    PLAYWRIGHT_CACHE="${HOME}/Library/Caches/ms-playwright"
    CHROMIUM_DIR=$(find "$PLAYWRIGHT_CACHE" -maxdepth 1 -type d -name "chromium-*" 2>/dev/null | head -n 1)
fi

if [ -n "$CHROMIUM_DIR" ]; then
    CHROMIUM_VERSION=$(basename "$CHROMIUM_DIR" | sed 's/chromium-//')
    echo "Found Chromium version: $CHROMIUM_VERSION"
    
    # Copy to the target location with the expected name format
    TARGET_DIR="$BROWSER_PATH/chromium_headless_shell-$CHROMIUM_VERSION"
    mkdir -p "$TARGET_DIR"
    cp -r "$CHROMIUM_DIR"/* "$TARGET_DIR/"
    
    echo "Copied Chromium $CHROMIUM_VERSION to $TARGET_DIR"
    echo "Browser files:"
    ls -la "$TARGET_DIR" | head -10
else
    echo "Warning: Could not find installed Chromium browser"
    echo "Attempting to install directly to target location..."
    
    # Set PLAYWRIGHT_BROWSERS_PATH and try installing again
    export PLAYWRIGHT_BROWSERS_PATH="$BROWSER_PATH"
    python3 -m playwright install chromium
    
    # Check if it worked
    if [ -d "$BROWSER_PATH" ]; then
        echo "Browser installation to target location successful"
        ls -la "$BROWSER_PATH"
        # Rename if needed
        CHROMIUM_DIR=$(find "$BROWSER_PATH" -maxdepth 1 -type d -name "chromium-*" | head -n 1)
        if [ -n "$CHROMIUM_DIR" ] && [[ "$CHROMIUM_DIR" != *"chromium_headless_shell"* ]]; then
            CHROMIUM_VERSION=$(basename "$CHROMIUM_DIR" | sed 's/chromium-//')
            mv "$CHROMIUM_DIR" "$BROWSER_PATH/chromium_headless_shell-$CHROMIUM_VERSION"
            echo "Renamed to chromium_headless_shell-$CHROMIUM_VERSION"
        fi
    fi
fi
