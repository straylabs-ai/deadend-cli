#!/usr/bin/env python3
"""
Test runner script for JSON-RPC server integration tests.

This script provides various testing modes:
- Quick tests (basic functionality)
- Integration tests (full server communication)
- Slow tests (component initialization)
- All tests
- Specific test files
- With coverage

Usage examples:
    # Run quick tests (default)
    python test_rpc_server.py
    python test_rpc_server.py --mode quick
    
    # Run all integration tests
    python test_rpc_server.py --mode integration
    
    # Run slow tests (requires Docker)
    python test_rpc_server.py --mode slow
    
    # Run with coverage
    python test_rpc_server.py --coverage
    
    # Run specific test
    python test_rpc_server.py --file integration/test_rpc_server.py::TestRPCServerIntegration::test_ping
    
    # Run with verbose output
    python test_rpc_server.py --verbose
    
    # Skip slow tests
    python test_rpc_server.py --markers "not slow"
    
    # Quick smoke tests
    python test_rpc_server.py quick
    
    # Slow tests only
    python test_rpc_server.py slow
"""

import sys
import subprocess
from pathlib import Path
import argparse
import os


def run_command(cmd, description=""):
    """Run a command and return the result"""
    print(f"\n{'='*50}")
    if description:
        print(f"Running: {description}")
    print(f"Command: {' '.join(cmd)}")
    print(f"{'='*50}\n")
    
    result = subprocess.run(cmd, capture_output=False, text=True, check=False)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description="Run JSON-RPC server integration tests")
    parser.add_argument(
        "--mode", 
        choices=["quick", "integration", "slow", "all"],
        default="quick",
        help="Test mode to run (default: quick)"
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Run with coverage reporting"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true", 
        help="Verbose output"
    )
    parser.add_argument(
        "--file", "-f",
        help="Run specific test file"
    )
    parser.add_argument(
        "--markers", "-m",
        help="Run tests with specific markers (e.g., 'not slow')"
    )
    parser.add_argument(
        "--parallel", "-n",
        type=int,
        help="Number of parallel workers (requires pytest-xdist)"
    )
    parser.add_argument(
        "--html-report",
        action="store_true",
        help="Generate HTML coverage report"
    )
    
    args = parser.parse_args()
    
    # Change to project root directory
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)
    
    # Base pytest command with uv
    cmd = ["uv", "run", "pytest", "-s"]
    
    # Add coverage if requested
    if args.coverage:
        cmd.extend([
            "--cov=src/deadend_cli/jsonrpc",
            "--cov-report=term-missing",
            "--cov-report=xml",
        ])
        
        if args.html_report:
            cmd.extend(["--cov-report=html"])
    
    # Add verbosity
    if args.verbose:
        cmd.append("-v")
    
    # Add parallel execution
    if args.parallel:
        cmd.extend(["-n", str(args.parallel)])
    
    # Add markers
    if args.markers:
        cmd.extend(["-m", args.markers])
    
    # Determine what to test
    if args.file:
        # Specific file
        if args.file.startswith("tests/"):
            test_path = args.file
        elif args.file.startswith("deadend_cli/tests/"):
            test_path = args.file.replace("deadend_cli/tests/", "tests/")
        else:
            test_path = f"tests/{args.file}"
        cmd.append(test_path)
    elif args.mode == "quick":
        # Quick tests only (basic functionality, no slow operations)
        cmd.extend([
            "tests/integration/test_rpc_server.py",
            "-m", "integration and not slow"
        ])
    elif args.mode == "integration":
        # All integration tests
        cmd.extend([
            "tests/integration/test_rpc_server.py",
            "-m", "integration"
        ])
    elif args.mode == "slow":
        # Slow tests only (component initialization)
        cmd.extend([
            "tests/integration/test_rpc_server.py",
            "-m", "slow"
        ])
    elif args.mode == "all":
        # All RPC server tests
        cmd.append("tests/integration/test_rpc_server.py")
    
    # Run the tests
    exit_code = run_command(cmd, f"RPC Server tests ({args.mode} mode)")
    
    if args.coverage and exit_code == 0:
        print("\n" + "="*50)
        print("Coverage Summary")
        print("="*50)
        
        # Show coverage summary
        subprocess.run(
            [
                "uv", "run", "coverage", "report", 
                "--include=src/deadend_cli/jsonrpc/*"
            ],
            check=False,
        )
        
        if args.html_report:
            print("\nHTML coverage report generated in htmlcov/")
            print("Open htmlcov/index.html in your browser to view")
    
    return exit_code


def run_quick_tests():
    """Run a quick subset of tests for development"""
    print("Running quick RPC server tests...")
    
    # Change to project root first
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)
    
    cmd = [
        "uv", "run", "pytest", "-s", "-v",
        "tests/integration/test_rpc_server.py::TestRPCServerIntegration::test_ping",
        "tests/integration/test_rpc_server.py::TestRPCServerIntegration::test_invalid_method",
        "tests/integration/test_rpc_server.py::TestRPCServerIntegration::test_concurrent_requests",
        "-m", "integration and not slow"
    ]
    
    return run_command(cmd, "Quick smoke tests")


def run_slow_tests():
    """Run slow tests that require component initialization"""
    print("Running slow RPC server tests...")
    print("WARNING: These tests may take several minutes and require Docker!")

    # Change to project root first
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)

    cmd = [
        "uv", "run", "pytest", "-s", "-v",
        "tests/integration/test_rpc_server.py",
        "-m", "slow"
    ]

    return run_command(cmd, "Slow integration tests")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "quick":
        test_exit_code = run_quick_tests()
    elif len(sys.argv) > 1 and sys.argv[1] == "slow":
        test_exit_code = run_slow_tests()
    else:
        test_exit_code = main()

    sys.exit(test_exit_code)
