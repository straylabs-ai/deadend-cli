#!/usr/bin/env bash
# Check which XBEN benchmarks have been successfully solved by grepping the flag
# from eval_metadata_file.json into the deadend_cli benchmark result logs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

XBEN_ROOT="$SCRIPT_DIR/xbow/validation-benchmarks/benchmarks"

START_NUM=1
END_NUM=104

usage() {
    echo "Usage: $0 [RESULTS_DIR]" >&2
    echo "  RESULTS_DIR: Directory containing .log result files (default: current directory)" >&2
    exit 1
}

require_cmd() {
    local cmd="$1"
    command -v "$cmd" >/dev/null 2>&1 || {
        echo "Missing required command: $cmd" >&2
        exit 1
    }
}

require_cmd jq
require_cmd grep

# Get results directory from argument or use current directory
if [[ $# -gt 1 ]]; then
    usage
fi

RESULTS_DIR="${1:-.}"
if [[ ! -d "$RESULTS_DIR" ]]; then
    echo "Error: Results directory does not exist: $RESULTS_DIR" >&2
    exit 1
fi

TOTAL=0
SUCCESS=0
FAILED=0
NOT_STARTED=0
SUCCESS_NUMS=()
FAILED_NUMS=()
NOT_STARTED_NUMS=()
TIMES=()

printf "Checking benchmarks from %d to %d\n" "$START_NUM" "$END_NUM"
printf "Results directory: %s\n" "$RESULTS_DIR"
printf "Metadata root    : %s\n" "$XBEN_ROOT"
echo "============================================================"

for (( num=START_NUM; num<=END_NUM; num++ )); do
    TOTAL=$((TOTAL + 1))
    BENCH_SLUG="$(printf "XBEN-%03d-24" "$num")"

    BENCH_DIR="$XBEN_ROOT/$BENCH_SLUG"
    META_FILE="$BENCH_DIR/eval_metadata_file.json"

    if [[ ! -d "$BENCH_DIR" || ! -f "$META_FILE" ]]; then
        printf "[NOT STARTED] %s (missing directory or %s)\n" "$BENCH_SLUG" "$(basename "$META_FILE")"
        NOT_STARTED=$((NOT_STARTED + 1))
        NOT_STARTED_NUMS+=("$num")
        continue
    fi

    solution="$(jq -r '.solution // empty' "$META_FILE" || true)"
    if [[ -z "$solution" ]]; then
        printf "[FAILED] %s (no solution field in metadata)\n" "$BENCH_SLUG"
        FAILED=$((FAILED + 1))
        FAILED_NUMS+=("$num")
        continue
    fi

    # Look for matching result files in RESULTS_DIR
    # They typically start with the benchmark slug, but we allow any match.
    # Support both .txt and .log extensions
    shopt -s nullglob
    mapfile -t candidate_files < <(find "$RESULTS_DIR" -maxdepth 1 -type f \( -name "${BENCH_SLUG}_*.txt" -o -name "*${BENCH_SLUG}*.txt" -o -name "${BENCH_SLUG}_*.log" -o -name "*${BENCH_SLUG}*.log" \))
    shopt -u nullglob

    if [[ ${#candidate_files[@]} -eq 0 ]]; then
        printf "[NOT STARTED] %s (no result files in %s)\n" "$BENCH_SLUG" "$RESULTS_DIR"
        NOT_STARTED=$((NOT_STARTED + 1))
        NOT_STARTED_NUMS+=("$num")
        continue
    fi

    found=false
    for f in "${candidate_files[@]}"; do
        if grep -qF "$solution" "$f"; then
            # Extract time from the log file (format: | Time (s) | 4349.969 |)
            time_line=$(grep -E '\| Time \(s\) \|' "$f" | tail -1 || true)
            if [[ -n "$time_line" ]]; then
                time_value=$(echo "$time_line" | awk -F'|' '{print $3}' | xargs)
                # Validate that time_value is a number (using awk to check)
                if [[ -n "$time_value" ]] && awk "BEGIN {exit !($time_value >= 0)}" 2>/dev/null; then
                    TIMES+=("$time_value")
                    printf "[SUCCESS] %s -> %s (Time: %s s)\n" "$BENCH_SLUG" "$(basename "$f")" "$time_value"
                else
                    printf "[SUCCESS] %s -> %s\n" "$BENCH_SLUG" "$(basename "$f")"
                fi
            else
                printf "[SUCCESS] %s -> %s\n" "$BENCH_SLUG" "$(basename "$f")"
            fi
            SUCCESS=$((SUCCESS + 1))
            SUCCESS_NUMS+=("$num")
            found=true
            break
        fi
    done

    if [[ "$found" == "false" ]]; then
        printf "[FAILED] %s (flag not found in %d result file(s))\n" "$BENCH_SLUG" "${#candidate_files[@]}"
        FAILED=$((FAILED + 1))
        FAILED_NUMS+=("$num")
    fi
done

echo "============================================================"
echo "Summary"
echo "============================================================"
printf "Benchmarks checked : %d\n" "$TOTAL"
printf "Successful         : %d\n" "$SUCCESS"
printf "Failed             : %d\n" "$FAILED"
printf "Not started        : %d\n" "$NOT_STARTED"
echo "============================================================"

started=$((TOTAL - NOT_STARTED))
if (( started > 0 )); then
    success_pct=$(awk "BEGIN { printf \"%.2f\", ($SUCCESS/$started)*100 }")
    fail_pct=$(awk "BEGIN { printf \"%.2f\", ($FAILED/$started)*100 }")
else
    success_pct="0.00"
    fail_pct="0.00"
fi

printf "Success ratio (started) : %d/%d (%.2f%%)\n" "$SUCCESS" "$started" "$success_pct"
printf "Failure ratio (started) : %d/%d (%.2f%%)\n" "$FAILED" "$started" "$fail_pct"
echo "============================================================"

if (( SUCCESS > 0 )); then
    printf "Successful benchmarks     : %s\n" "${SUCCESS_NUMS[*]}"
fi
if (( FAILED > 0 )); then
    printf "Failed benchmarks         : %s\n" "${FAILED_NUMS[*]}"
fi
if (( NOT_STARTED > 0 )); then
    printf "Not started benchmarks    : %s\n" "${NOT_STARTED_NUMS[*]}"
fi
echo "============================================================"

# Calculate average, minimum, and maximum time for successful benchmarks
if (( SUCCESS > 0 && ${#TIMES[@]} > 0 )); then
    total_time=0
    min_time=""
    max_time=""
    for time_val in "${TIMES[@]}"; do
        total_time=$(awk "BEGIN { printf \"%.3f\", $total_time + $time_val }")
        if [[ -z "$min_time" ]] || awk "BEGIN { exit !($time_val < $min_time) }" 2>/dev/null; then
            min_time="$time_val"
        fi
        if [[ -z "$max_time" ]] || awk "BEGIN { exit !($time_val > $max_time) }" 2>/dev/null; then
            max_time="$time_val"
        fi
    done
    avg_time_sec=$(awk "BEGIN { printf \"%.3f\", $total_time / ${#TIMES[@]} }")
    avg_time_min=$(awk "BEGIN { printf \"%.3f\", $avg_time_sec / 60 }")
    min_time_min=$(awk "BEGIN { printf \"%.3f\", $min_time / 60 }")
    max_time_min=$(awk "BEGIN { printf \"%.3f\", $max_time / 60 }")
    printf "Average time (successful) : %.3f seconds (%.3f minutes)\n" "$avg_time_sec" "$avg_time_min"
    printf "Minimum time (successful) : %.3f seconds (%.3f minutes)\n" "$min_time" "$min_time_min"
    printf "Maximum time (successful) : %.3f seconds (%.3f minutes)\n" "$max_time" "$max_time_min"
    echo "============================================================"
fi

