#!/usr/bin/env python3
"""
Test runner script for sandbox component tests.

This script provides various testing modes:
- Unit tests only
- Integration tests only
- All tests
- Specific test files
- Performance tests
- With coverage
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
    print(f"{'='*50}")
    
    result = subprocess.run(cmd, capture_output=False, text=True)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description="Run sandbox component tests")
    parser.add_argument(
        "--mode", 
        choices=["unit", "integration", "all", "performance"],
        default="all",
        help="Test mode to run"
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
    project_root = Path(__file__).parent
    os.chdir(project_root)
    
    # Base pytest command with uv
    cmd = ["uv", "run", "pytest", "-s"]
    
    # Add coverage if requested
    if args.coverage:
        cmd.extend([
            "--cov=src/core/sandbox",
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
        test_path = f"tests/{args.file}" if not args.file.startswith("tests/") else args.file
        cmd.append(test_path)
    elif args.mode == "unit":
        # Unit tests only
        cmd.extend([
            "tests/unit/test_sandbox_core.py",
            "tests/unit/test_sandbox_manager.py"
        ])
    elif args.mode == "integration":
        # Integration tests only
        cmd.append("tests/integration/test_sandbox_integration.py")
        cmd.extend(["-m", "integration"])
    elif args.mode == "performance":
        # Performance tests
        cmd.extend(["-m", "slow"])
        cmd.append("tests/integration/test_sandbox_integration.py")
    elif args.mode == "all":
        # All sandbox tests
        cmd.extend([
            "tests/unit/test_sandbox_core.py",
            "tests/unit/test_sandbox_manager.py", 
            "tests/integration/test_sandbox_integration.py"
        ])
    
    # Run the tests
    exit_code = run_command(cmd, f"Sandbox tests ({args.mode} mode)")
    
    if args.coverage and exit_code == 0:
        print("\n" + "="*50)
        print("Coverage Summary")
        print("="*50)
        
        # Show coverage summary
        subprocess.run([
            "uv", "run", "coverage", "report", 
            "--include=src/core/sandbox/*"
        ])
        
        if args.html_report:
            print("\nHTML coverage report generated in htmlcov/")
            print("Open htmlcov/index.html in your browser to view")
    
    return exit_code


def run_quick_tests():
    """Run a quick subset of tests for development"""
    print("Running quick sandbox tests...")
    
    cmd = [
        "uv", "run", "pytest", "-s",
        "tests/unit/test_sandbox_core.py::TestSandbox::test_sandbox_initialization",
        "tests/unit/test_sandbox_core.py::TestSandbox::test_start_success_no_volume", 
        "tests/unit/test_sandbox_manager.py::TestSandboxManager::test_create_sandbox_default_image",
        "-v"
    ]
    
    return run_command(cmd, "Quick smoke tests")


def run_docker_tests():
    """Run tests that require Docker (with actual containers)"""
    print("Running Docker integration tests...")
    print("WARNING: These tests require Docker to be running!")
    
    cmd = [
        "uv", "run", "pytest", "-s",
        "tests/integration/test_sandbox_integration.py",
        "-m", "docker",
        "-v"
    ]
    
    return run_command(cmd, "Docker integration tests")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "quick":
        exit_code = run_quick_tests()
    elif len(sys.argv) > 1 and sys.argv[1] == "docker":
        exit_code = run_docker_tests()
    else:
        exit_code = main()
    
    sys.exit(exit_code)