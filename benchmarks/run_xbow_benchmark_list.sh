#!/usr/bin/env bash
# Run XBEN benchmarks for a list of specific benchmark numbers.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BENCHMARK_SCRIPT="$SCRIPT_DIR/run_xbow_benchmark.sh"
XBEN_ROOT="$SCRIPT_DIR/xbow/validation-benchmarks/benchmarks"
RESULTS_BASE_DIR="$REPO_ROOT/benchmarks-results/xbow"

usage() {
    cat >&2 <<EOF
Usage: $0 [--stop-on-error] <benchmark-number> [benchmark-number ...]

Runs run_xbow_benchmark.sh for each specified benchmark number.

Arguments:
  --stop-on-error   Stop execution if a benchmark fails (default: continue)
  benchmark-number  One or more benchmark numbers to run (positive integers)

Examples:
  $0 1 5 10              # Run benchmarks 1, 5, and 10
  $0 --stop-on-error 25 30 35  # Run 25, 30, 35, stop on first error
  $0 1 2 3 4 5           # Run benchmarks 1 through 5
EOF
    exit 1
}

if [[ $# -lt 1 ]]; then
    usage
fi

STOP_ON_ERROR=false
BENCH_NUMS=()

# Parse arguments
for arg in "$@"; do
    if [[ "$arg" == "--stop-on-error" ]]; then
        STOP_ON_ERROR=true
    elif [[ "$arg" =~ ^[0-9]+$ ]]; then
        if (( arg <= 0 )); then
            echo "Benchmark number must be a positive integer: $arg" >&2
            exit 1
        fi
        BENCH_NUMS+=("$arg")
    else
        echo "Invalid argument: $arg" >&2
        usage
    fi
done

if [[ ${#BENCH_NUMS[@]} -eq 0 ]]; then
    echo "Error: At least one benchmark number must be provided." >&2
    usage
fi

if [[ ! -f "$BENCHMARK_SCRIPT" ]]; then
    echo "Benchmark script not found: $BENCHMARK_SCRIPT" >&2
    exit 1
fi

if [[ ! -x "$BENCHMARK_SCRIPT" ]]; then
    echo "Making benchmark script executable: $BENCHMARK_SCRIPT"
    chmod +x "$BENCHMARK_SCRIPT"
fi

# Create results directory for this run
RUN_NAME="run-$(date +%Y%m%d-%H%M%S)"
OUTPUT_DIR="$RESULTS_BASE_DIR/$RUN_NAME"
mkdir -p "$OUTPUT_DIR"
echo "[+] Results will be saved to: $OUTPUT_DIR"

TIMEOUT_SECONDS=1800
TIMEOUT_MINUTES=$((TIMEOUT_SECONDS / 60))

if ! command -v timeout >/dev/null 2>&1; then
    echo "Warning: 'timeout' command not found. Timeout functionality will be disabled." >&2
    TIMEOUT_AVAILABLE=false
else
    TIMEOUT_AVAILABLE=true
fi

TOTAL=${#BENCH_NUMS[@]}
CURRENT=0
SUCCESS=0
FAILED=0
TIMED_OUT=0
INTERRUPTED=0
FAILED_NUMS=()
TIMED_OUT_NUMS=()
INTERRUPTED_NUMS=()
CURRENT_BENCH_NUM=""
CURRENT_BENCH_DIR=""
HANDLING_INTERRUPT=false
SKIP_TO_NEXT=false

cleanup_current_benchmark() {
    if [[ -n "$CURRENT_BENCH_DIR" && -d "$CURRENT_BENCH_DIR" ]]; then
        echo ""
        echo "[!] Cleaning up current benchmark: $CURRENT_BENCH_NUM"
        (cd "$CURRENT_BENCH_DIR" && make stop 2>/dev/null || true) || true
    fi
}

interrupt_handler() {
    if [[ "$HANDLING_INTERRUPT" == "true" ]]; then
        echo ""
        echo "[!] Force exit requested"
        cleanup_current_benchmark
        exit 130
    fi
    
    HANDLING_INTERRUPT=true
    echo ""
    echo ""
    echo "[!] Interrupted (Ctrl+C) during benchmark $CURRENT_BENCH_NUM"
    cleanup_current_benchmark
    
    INTERRUPTED=$((INTERRUPTED + 1))
    if [[ -n "$CURRENT_BENCH_NUM" ]]; then
        INTERRUPTED_NUMS+=("$CURRENT_BENCH_NUM")
    fi
    
    echo ""
    echo "Options:"
    echo "  1) Continue with next benchmark (default)"
    echo "  2) Exit and show summary"
    echo "  (Press Ctrl+C again to force exit)"
    echo ""
    read -t 10 -p "Choice [1/2] (default: 1): " choice || choice=1
    
    if [[ "$choice" == "2" ]]; then
        echo "[!] Exiting due to user request"
        HANDLING_INTERRUPT=false
        show_summary_and_exit
    else
        echo "[+] Continuing with next benchmark..."
        SKIP_TO_NEXT=true
        HANDLING_INTERRUPT=false
        echo ""
    fi
}

show_summary_and_exit() {
    echo ""
    echo "=========================================="
    echo "Summary (interrupted)"
    echo "=========================================="
    echo "Total benchmarks: $TOTAL"
    echo "Processed: $CURRENT"
    echo "Successful: $SUCCESS"
    echo "Failed: $FAILED"
    echo "Timed out: $TIMED_OUT"
    echo "Interrupted: $INTERRUPTED"
    if [[ ${#FAILED_NUMS[@]} -gt 0 ]]; then
        echo "Failed benchmark numbers: ${FAILED_NUMS[*]}"
    fi
    if [[ ${#TIMED_OUT_NUMS[@]} -gt 0 ]]; then
        echo "Timed out benchmark numbers: ${TIMED_OUT_NUMS[*]}"
    fi
    if [[ ${#INTERRUPTED_NUMS[@]} -gt 0 ]]; then
        echo "Interrupted benchmark numbers: ${INTERRUPTED_NUMS[*]}"
    fi
    echo "=========================================="
    exit 130
}

trap interrupt_handler INT
trap 'cleanup_current_benchmark; exit 130' TERM

echo "=========================================="
echo "Running XBEN benchmarks: ${BENCH_NUMS[*]}"
echo "Total benchmarks: $TOTAL"
echo "Results directory: $OUTPUT_DIR"
if [[ "$STOP_ON_ERROR" == "true" ]]; then
    echo "Mode: Stop on first error"
else
    echo "Mode: Continue on errors"
fi
if [[ "$TIMEOUT_AVAILABLE" == "true" ]]; then
    echo "Timeout: ${TIMEOUT_MINUTES} minutes per benchmark"
fi
echo "=========================================="
echo

for num in "${BENCH_NUMS[@]}"; do
    SKIP_TO_NEXT=false
    CURRENT=$((CURRENT + 1))
    BENCH_SLUG="$(printf "XBEN-%03d-24" "$num")"
    CURRENT_BENCH_NUM="$num"
    CURRENT_BENCH_DIR="$XBEN_ROOT/$BENCH_SLUG"
    
    echo "=========================================="
    echo "[$CURRENT/$TOTAL] Processing $BENCH_SLUG (benchmark #$num)"
    if [[ "$TIMEOUT_AVAILABLE" == "true" ]]; then
        echo "Timeout: ${TIMEOUT_MINUTES} minutes"
    fi
    echo "Press Ctrl+C to interrupt current benchmark"
    echo "=========================================="
    
    start_time=$(date +%s)
    timed_out=false
    
    if [[ "$TIMEOUT_AVAILABLE" == "true" ]]; then
        if timeout "$TIMEOUT_SECONDS" env OUTPUT_DIR="$OUTPUT_DIR" "$BENCHMARK_SCRIPT" "$num"; then
            exit_code=0
        else
            exit_code=$?
            if [[ $exit_code -eq 124 ]]; then
                timed_out=true
            elif [[ $exit_code -eq 130 ]]; then
                exit_code=130
            fi
        fi
    else
        if env OUTPUT_DIR="$OUTPUT_DIR" "$BENCHMARK_SCRIPT" "$num"; then
            exit_code=0
        else
            exit_code=$?
            if [[ $exit_code -eq 130 ]]; then
                exit_code=130
            fi
        fi
    fi
    
    if [[ "$SKIP_TO_NEXT" == "true" ]]; then
        SKIP_TO_NEXT=false
        CURRENT_BENCH_NUM=""
        CURRENT_BENCH_DIR=""
        echo ""
        continue
    fi
    
    if [[ $exit_code -eq 130 ]]; then
        INTERRUPTED=$((INTERRUPTED + 1))
        INTERRUPTED_NUMS+=("$num")
        echo "[!] $BENCH_SLUG was interrupted"
        cleanup_current_benchmark
        CURRENT_BENCH_NUM=""
        CURRENT_BENCH_DIR=""
        echo ""
        continue
    fi
    
    end_time=$(date +%s)
    elapsed=$((end_time - start_time))
    elapsed_min=$((elapsed / 60))
    elapsed_sec=$((elapsed % 60))
    
    if [[ "$timed_out" == "true" ]]; then
        TIMED_OUT=$((TIMED_OUT + 1))
        TIMED_OUT_NUMS+=("$num")
        echo "[⏱] $BENCH_SLUG timed out after ${elapsed_min}m ${elapsed_sec}s (${TIMEOUT_MINUTES} min limit)"
        echo "[!] Cleaning up any remaining processes for $BENCH_SLUG..."
        
        BENCH_DIR="$XBEN_ROOT/$BENCH_SLUG"
        if [[ -d "$BENCH_DIR" ]]; then
            (cd "$BENCH_DIR" && make stop 2>/dev/null || true) || true
        fi
        
        if [[ "$STOP_ON_ERROR" == "true" ]]; then
            echo "Stopping due to --stop-on-error flag"
            break
        fi
    elif [[ $exit_code -eq 0 ]]; then
        SUCCESS=$((SUCCESS + 1))
        echo "[✓] $BENCH_SLUG completed successfully in ${elapsed_min}m ${elapsed_sec}s"
    else
        FAILED=$((FAILED + 1))
        FAILED_NUMS+=("$num")
        echo "[✗] $BENCH_SLUG failed after ${elapsed_min}m ${elapsed_sec}s (exit code: $exit_code)"
        
        if [[ "$STOP_ON_ERROR" == "true" ]]; then
            echo "Stopping due to --stop-on-error flag"
            break
        fi
    fi
    
    CURRENT_BENCH_NUM=""
    CURRENT_BENCH_DIR=""
    echo
done

trap - INT TERM

echo "=========================================="
echo "Summary"
echo "=========================================="
echo "Total benchmarks: $TOTAL"
echo "Successful: $SUCCESS"
echo "Failed: $FAILED"
echo "Timed out: $TIMED_OUT"
echo "Interrupted: $INTERRUPTED"
if [[ ${#FAILED_NUMS[@]} -gt 0 ]]; then
    echo "Failed benchmark numbers: ${FAILED_NUMS[*]}"
fi
if [[ ${#TIMED_OUT_NUMS[@]} -gt 0 ]]; then
    echo "Timed out benchmark numbers: ${TIMED_OUT_NUMS[*]}"
fi
if [[ ${#INTERRUPTED_NUMS[@]} -gt 0 ]]; then
    echo "Interrupted benchmark numbers: ${INTERRUPTED_NUMS[*]}"
fi
echo "=========================================="

if [[ $FAILED -gt 0 || $TIMED_OUT -gt 0 || $INTERRUPTED -gt 0 ]]; then
    exit 1
fi

