#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values
INSTALL_DIR="${INSTALL_DIR:-$HOME/.cache/server}"
VERSION="${VERSION:-latest}"
REPO="${REPO:-xoxruns/deadend-cli}"

# Detect OS and architecture
detect_platform() {
    local os=""
    local arch=""
    
    case "$(uname -s)" in
        Linux*)
            os="linux"
            ;;
        Darwin*)
            os="macos"
            ;;
        *)
            echo -e "${RED}Error: Unsupported operating system: $(uname -s)${NC}"
            exit 1
            ;;
    esac
    
    case "$(uname -m)" in
        x86_64)
            arch="x86_64"
            ;;
        arm64|aarch64)
            arch="aarch64"
            ;;
        *)
            echo -e "${RED}Error: Unsupported architecture: $(uname -m)${NC}"
            exit 1
            ;;
    esac
    
    if [ "$os" == "linux" ]; then
        PLATFORM="linux"
        TARGET="x86_64-unknown-linux-gnu"
    else
        PLATFORM="macos"
        # Only support ARM64 for macOS
        if [ "$arch" != "aarch64" ]; then
            echo -e "${YELLOW}Warning: x86_64 macOS is not supported. Using ARM64 build.${NC}"
        fi
        TARGET="aarch64-apple-darwin"
    fi
    
    PACKAGE_NAME="deadend-${PLATFORM}-${TARGET}"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --version)
            VERSION="$2"
            shift 2
            ;;
        --install-dir)
            INSTALL_DIR="$2"
            shift 2
            ;;
        --repo)
            REPO="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --version VERSION     Version to install (default: latest)"
            echo "  --install-dir DIR     Installation directory (default: ~/.cache/server)"
            echo "  --repo REPO           GitHub repository (default: xoxruns/deadend-cli)"
            echo "  -h, --help            Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done


# Get the latest release version
get_latest_version() {
    if [ "$VERSION" == "latest" ]; then
        VERSION=$(curl -s "https://api.github.com/repos/${REPO}/releases/latest" | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/')
        if [ -z "$VERSION" ]; then
            echo -e "${RED}Error: Could not determine latest version${NC}"
            exit 1
        fi
    fi
}

# Install
install() {
    echo -e "${GREEN}Installing Deadend CLI Server ${VERSION} for ${PLATFORM}...${NC}"
    
    # Create temporary directory
    TEMP_DIR=$(mktemp -d)
    trap "rm -rf $TEMP_DIR" EXIT
    
    # Download the release
    DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${VERSION}/${PACKAGE_NAME}.tar.gz"
    echo -e "${YELLOW}Downloading from: ${DOWNLOAD_URL}${NC}"
    
    if ! curl -fsSL -o "${TEMP_DIR}/${PACKAGE_NAME}.tar.gz" "$DOWNLOAD_URL"; then
        echo -e "${RED}Error: Failed to download release${NC}"
        exit 1
    fi
    
    # Verify checksum if available
    CHECKSUM_URL="https://github.com/${REPO}/releases/download/${VERSION}/${PACKAGE_NAME}.tar.gz.sha256"
    if curl -fsSL -o "${TEMP_DIR}/${PACKAGE_NAME}.tar.gz.sha256" "$CHECKSUM_URL" 2>/dev/null; then
        echo -e "${YELLOW}Verifying checksum...${NC}"
        cd "$TEMP_DIR"
        # Fix checksum file if it contains a path - replace with just the filename
        if grep -q "/" "${PACKAGE_NAME}.tar.gz.sha256" 2>/dev/null; then
            # Extract hash and filename, then rewrite with just filename
            hash=$(awk '{print $1}' "${PACKAGE_NAME}.tar.gz.sha256" | head -1)
            echo "${hash}  ${PACKAGE_NAME}.tar.gz" > "${PACKAGE_NAME}.tar.gz.sha256"
        fi
        if command -v sha256sum >/dev/null 2>&1; then
            sha256sum -c "${PACKAGE_NAME}.tar.gz.sha256" || {
                echo -e "${RED}Error: Checksum verification failed${NC}"
                exit 1
            }
        elif command -v shasum >/dev/null 2>&1; then
            shasum -a 256 -c "${PACKAGE_NAME}.tar.gz.sha256" || {
                echo -e "${RED}Error: Checksum verification failed${NC}"
                exit 1
            }
        fi
        echo -e "${GREEN}Checksum verified${NC}"
    else
        echo -e "${YELLOW}Warning: Checksum file not found, skipping verification${NC}"
    fi
    
    # Extract
    echo -e "${YELLOW}Extracting package...${NC}"
    cd "$TEMP_DIR"
    tar -xzf "${PACKAGE_NAME}.tar.gz"
    
    # Create installation directory
    echo -e "${YELLOW}Installing to ${INSTALL_DIR}...${NC}"
    mkdir -p "$INSTALL_DIR"
    
    # Copy entire package contents (includes deadend binary, deadend.sh, lib/, etc.)
    if [ -d "${PACKAGE_NAME}" ]; then
        cp -r "${PACKAGE_NAME}"/* "${INSTALL_DIR}/"
        chmod +x "${INSTALL_DIR}/deadend" 2>/dev/null || true
        chmod +x "${INSTALL_DIR}/deadend.sh" 2>/dev/null || true
        
        # Fix permissions for Playwright driver
        if [ -f "${INSTALL_DIR}/lib/playwright/driver/node" ]; then
            chmod +x "${INSTALL_DIR}/lib/playwright/driver/node"
        fi
        
        echo -e "${GREEN}Package installed to ${INSTALL_DIR}${NC}"
    else
        echo -e "${RED}Error: Package directory not found${NC}"
        exit 1
    fi
    
    echo ""
    echo -e "${GREEN}Installation complete!${NC}"
    echo ""
    echo "The Deadend CLI server is installed at:"
    echo "  ${INSTALL_DIR}/deadend.sh"
    echo ""
    echo "You can set DEADEND_RPC_BINARY environment variable to use a custom path:"
    echo "  export DEADEND_RPC_BINARY=\"${INSTALL_DIR}/deadend.sh\""
    echo ""
}

# Main
main() {
    echo -e "${GREEN}Deadend CLI Server Installer${NC}"
    echo ""
    
    detect_platform
    get_latest_version
    
    echo -e "${YELLOW}Platform: ${PLATFORM}${NC}"
    echo -e "${YELLOW}Target: ${TARGET}${NC}"
    echo -e "${YELLOW}Version: ${VERSION}${NC}"
    echo -e "${YELLOW}Install directory: ${INSTALL_DIR}${NC}"
    echo ""
    
    # Skip confirmation if running non-interactively
    if [ -t 0 ]; then
        read -p "Continue with installation? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Installation cancelled"
            exit 0
        fi
    fi
    
    install
}

main "$@"
