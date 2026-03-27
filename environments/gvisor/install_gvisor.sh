#!/bin/bash

# Script to install gVisor with prerequisite checks
# Checks for Docker and sudo privileges before installation

set -e

# ANSI color codes for better output readability
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# Function to print colored messages
print_status() {
    case $1 in
        "info")
            echo -e "${YELLOW}[INFO]${NC} $2"
            ;;
        "success")
            echo -e "${GREEN}[SUCCESS]${NC} $2"
            ;;
        "error")
            echo -e "${RED}[ERROR]${NC} $2"
            ;;
    esac
}

# Check root
check_sudo() {
    print_status "info" "Checking for sudo privileges..."
    
    if [ "$(id -u)" -ne 0 ]; then
        print_status "error" "This script must be run with sudo privileges."
        print_status "error" "Please run: sudo $0"
        exit 1
    fi
    
    print_status "success" "Script is running with sudo privileges."
}

# Check if Docker is installed and running
check_docker() {
    print_status "info" "Checking Docker installation..."
    
    if ! command -v docker &> /dev/null; then
        print_status "error" "Docker is not installed."
        print_status "error" "Please install Docker first: https://docs.docker.com/get-docker/"
        exit 1
    fi
    
    print_status "success" "Docker is installed."
    
    print_status "info" "Checking if Docker daemon is running..."
    
    if ! docker info &> /dev/null; then
        print_status "error" "Docker daemon is not running."
        print_status "error" "Please start Docker service with: sudo systemctl start docker"
        exit 1
    fi
    
    print_status "success" "Docker daemon is running."
}

# Install gVisor
install_gvisor() {
    print_status "info" "Beginning gVisor installation..."
    
    # Set up the repository
    ARCH=$(uname -m)
    URL=https://storage.googleapis.com/gvisor/releases/release/latest/${ARCH}
    
    # Download and install gVisor components
    wget ${URL}/runsc ${URL}/runsc.sha512 \
    ${URL}/containerd-shim-runsc-v1 ${URL}/containerd-shim-runsc-v1.sha512
    sha512sum -c runsc.sha512 \
    -c containerd-shim-runsc-v1.sha512
    rm -f *.sha512
    # Make them executable
    chmod a+rx runsc containerd-shim-runsc-v1
    sudo mv runsc containerd-shim-runsc-v1 /usr/local/bin
    # Configure Docker to use gVisor
    mkdir -p /etc/docker
    
    # Check if /etc/docker/daemon.json exists
    if [ -f /etc/docker/daemon.json ]; then
        print_status "info" "Backing up existing Docker daemon configuration..."
        cp /etc/docker/daemon.json /etc/docker/daemon.json.bak
    else
        print_status "info" "Creating Docker daemon configuration file..."
        sudo touch /etc/docker/daemon.json
 
    fi
    print_status "info" "Installing runsc runtime"
    sudo runsc install

    print_status "info" "Adding overlay memory to runtime runsc"
    sudo jq '.runtimes.runsc +={runtimeArgs: ["--overlay2=all:memory"]}' ./daemon.json > /etc/docker/daemon.json
    cat /etc/docker/daemon.json
    # Restart Docker to apply changes
    print_status "info" "Restarting Docker service to apply changes..."
    systemctl restart docker
    
    # Verify installation
    print_status "info" "Verifying gVisor installation..."
    if docker info | grep -q runsc; then
        print_status "success" "gVisor has been successfully installed and configured!"
        print_status "info" "You can now run containers with gVisor using: docker run --runtime=runsc ..."
    else
        print_status "error" "gVisor installation verification failed."
        print_status "error" "Please check Docker configuration and restart the service manually."
        exit 1
    fi
}

test_run_hello_world() {
    # Run test with hello-world container and runsc runtime
    print_status "info" "Testing runsc runtime with hello-world"
    if docker run --rm --runtime=runsc hello-world | grep "Hello from Docker!"; then
        print_status "success" "gVisor hello-world test successful."
    else
        print_status "error" "gVisor hello-world test failed."
    fi
}

# Main execution
main() {
    echo "====== gVisor Installation Script ======"
    
    # Check prerequisites
    check_sudo
    check_docker
    
    # Install gVisor
    install_gvisor

    # test hello-world container
    test_run_hello_world

    echo "====== Installation Complete ======"
}

# Run the main function
main