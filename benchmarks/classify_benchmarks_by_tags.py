#!/usr/bin/env python3
"""
Classify XBEN benchmarks by their tags from benchmark.json files.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def number_to_benchmark_id(num):
    """Convert a number to XBEN-XXX-24 format."""
    return f"XBEN-{num:03d}-24"


def parse_benchmark_numbers(numbers_list):
    """Parse a space-separated list of numbers and ranges.
    
    Examples:
        ["1", "2", "3"] -> [1, 2, 3]
        ["1-5"] -> [1, 2, 3, 4, 5]
        ["1", "3-5", "10"] -> [1, 3, 4, 5, 10]
    """
    numbers = set()
    
    for part in numbers_list:
        part = part.strip()
        if not part:
            continue
        
        if '-' in part:
            # Handle range (e.g., "1-5")
            try:
                start, end = part.split('-', 1)
                start_num = int(start)
                end_num = int(end)
                if start_num > end_num:
                    start_num, end_num = end_num, start_num
                numbers.update(range(start_num, end_num + 1))
            except ValueError:
                print(f"Warning: Invalid range format '{part}', skipping", file=sys.stderr)
        else:
            # Handle single number
            try:
                numbers.add(int(part))
            except ValueError:
                print(f"Warning: Invalid number '{part}', skipping", file=sys.stderr)
    
    return sorted(numbers)


def find_benchmark_dirs(benchmarks_root, filter_numbers=None):
    """Find all XBEN-XXX-24 directories, optionally filtered by numbers.
    
    Returns:
        tuple: (filtered_benchmark_dirs, total_count)
    """
    benchmark_dirs = []
    total_count = 0
    benchmarks_path = Path(benchmarks_root)
    
    if not benchmarks_path.exists():
        print(f"Error: Benchmarks directory does not exist: {benchmarks_root}", file=sys.stderr)
        sys.exit(1)
    
    # If filter_numbers is provided, create a set of benchmark IDs to include
    filter_ids = None
    if filter_numbers:
        filter_ids = {number_to_benchmark_id(num) for num in filter_numbers}
    
    for item in benchmarks_path.iterdir():
        if item.is_dir() and item.name.startswith("XBEN-") and item.name.endswith("-24"):
            total_count += 1
            if filter_ids is None or item.name in filter_ids:
                benchmark_dirs.append(item)
    
    return sorted(benchmark_dirs), total_count


def extract_tags(benchmark_dir):
    """Extract tags from benchmark.json in the given directory."""
    benchmark_json = benchmark_dir / "benchmark.json"
    
    if not benchmark_json.exists():
        return None, None
    
    try:
        with open(benchmark_json, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        tags = data.get("tags", [])
        name = data.get("name", benchmark_dir.name)
        level = data.get("level", "unknown")
        
        return tags, {"name": name, "level": level}
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not read {benchmark_json}: {e}", file=sys.stderr)
        return None, None


def classify_benchmarks(benchmarks_root, filter_numbers=None):
    """Classify all benchmarks by their tags, optionally filtered by numbers.
    
    Returns:
        tuple: (tag_to_benchmarks, benchmark_to_tags, no_tags, total_count, tag_total_counts)
    """
    benchmark_dirs, total_count = find_benchmark_dirs(benchmarks_root, filter_numbers)
    
    # Dictionary: tag -> list of (benchmark_id, metadata) for filtered benchmarks
    tag_to_benchmarks = defaultdict(list)
    
    # Dictionary: benchmark_id -> tags
    benchmark_to_tags = {}
    
    # Track benchmarks without tags
    no_tags = []
    
    for bench_dir in benchmark_dirs:
        bench_id = bench_dir.name
        tags, metadata = extract_tags(bench_dir)
        
        if tags is None:
            continue
        
        if not tags:
            no_tags.append((bench_id, metadata))
        else:
            benchmark_to_tags[bench_id] = tags
            for tag in tags:
                tag_to_benchmarks[tag].append((bench_id, metadata))
    
    # Calculate total tag counts from all benchmarks (not filtered)
    tag_total_counts = defaultdict(int)
    if filter_numbers:
        # Only calculate totals if filtering is applied
        all_benchmark_dirs, _ = find_benchmark_dirs(benchmarks_root, None)
        for bench_dir in all_benchmark_dirs:
            tags, _ = extract_tags(bench_dir)
            if tags:
                for tag in tags:
                    tag_total_counts[tag] += 1
    
    return tag_to_benchmarks, benchmark_to_tags, no_tags, total_count, tag_total_counts


def print_classification(tag_to_benchmarks, benchmark_to_tags, no_tags, total_count, tag_total_counts=None, filter_numbers=None):
    """Print the classification results."""
    print("=" * 80)
    print("XBEN Benchmark Classification by Tags")
    if filter_numbers:
        filter_str = ", ".join(str(n) for n in filter_numbers)
        print(f"Filtered to benchmarks: {filter_str}")
        included = len(benchmark_to_tags) + len(no_tags)
        excluded = total_count - included
        print(f"Included: {included} | Excluded: {excluded} | Total: {total_count}")
    print("=" * 80)
    print()
    
    # Summary statistics
    total_benchmarks = len(benchmark_to_tags) + len(no_tags)
    total_tags = len(tag_to_benchmarks)
    
    print(f"Total benchmarks: {total_benchmarks}")
    print(f"Total unique tags: {total_tags}")
    print(f"Benchmarks with tags: {len(benchmark_to_tags)}")
    print(f"Benchmarks without tags: {len(no_tags)}")
    print()
    
    # Tag statistics
    print("=" * 80)
    print("Tag Statistics (sorted by frequency)")
    print("=" * 80)
    print()
    
    tag_counts = [(tag, len(benchmarks)) for tag, benchmarks in tag_to_benchmarks.items()]
    tag_counts.sort(key=lambda x: (-x[1], x[0]))  # Sort by count (desc), then by name
    
    for tag, count in tag_counts:
        if tag_total_counts and tag in tag_total_counts:
            total = tag_total_counts[tag]
            # Percentage: filtered count / total count for this tag
            pct = (count / total * 100) if total > 0 else 0
            print(f"  {tag:30s} : {count:3d} benchmark(s) ({total} total) - {pct:5.1f}%%")
        else:
            print(f"  {tag:30s} : {count:3d} benchmark(s)")
    print()
    
    # Detailed classification by tag
    print("=" * 80)
    print("Classification by Tag")
    print("=" * 80)
    print()
    
    for tag, count in tag_counts:
        print(f"Tag: {tag} ({count} benchmark(s))")
        print("-" * 80)
        
        # Sort benchmarks by ID
        benchmarks = sorted(tag_to_benchmarks[tag], key=lambda x: x[0])
        
        for bench_id, metadata in benchmarks:
            level = metadata.get("level", "unknown") if metadata else "unknown"
            name = metadata.get("name", bench_id) if metadata else bench_id
            print(f"  {bench_id:15s} [Level {level}] {name}")
        
        print()
    
    # Benchmarks without tags
    if no_tags:
        print("=" * 80)
        print(f"Benchmarks without tags ({len(no_tags)})")
        print("=" * 80)
        print()
        
        for bench_id, metadata in sorted(no_tags, key=lambda x: x[0]):
            level = metadata.get("level", "unknown") if metadata else "unknown"
            name = metadata.get("name", bench_id) if metadata else bench_id
            print(f"  {bench_id:15s} [Level {level}] {name}")
        print()
    
    # Benchmarks with multiple tags
    print("=" * 80)
    print("Benchmarks with Multiple Tags")
    print("=" * 80)
    print()
    
    multi_tag_benchmarks = [(bid, tags) for bid, tags in benchmark_to_tags.items() if len(tags) > 1]
    multi_tag_benchmarks.sort(key=lambda x: (-len(x[1]), x[0]))  # Sort by tag count (desc), then by ID
    
    if multi_tag_benchmarks:
        for bench_id, tags in multi_tag_benchmarks:
            tags_str = ", ".join(sorted(tags))
            print(f"  {bench_id:15s} : {tags_str}")
    else:
        print("  (none)")
    print()


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Classify XBEN benchmarks by their tags from benchmark.json files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s
    Classify all benchmarks

  %(prog)s --benchmarks 1 2 3
    Classify only benchmarks 1, 2, and 3

  %(prog)s --benchmarks 1-10
    Classify benchmarks 1 through 10

  %(prog)s --benchmarks 1 3-5 10
    Classify benchmarks 1, 3, 4, 5, and 10

  %(prog)s --benchmarks 1-5 --benchmarks-root /custom/path
    Use custom benchmarks root directory
        """
    )
    
    parser.add_argument(
        '--benchmarks', '-b',
        nargs='+',
        type=str,
        help='Space-separated list of benchmark numbers or ranges (e.g., "1 2 3" or "1-10" or "1 3-5 10")'
    )
    
    parser.add_argument(
        '--benchmarks-root',
        type=str,
        help='Root directory containing XBEN benchmarks (default: ./xbow/validation-benchmarks/benchmarks)'
    )
    
    args = parser.parse_args()
    
    # Determine benchmarks root directory
    script_dir = Path(__file__).parent
    if args.benchmarks_root:
        benchmarks_root = Path(args.benchmarks_root)
    else:
        benchmarks_root = script_dir / "xbow" / "validation-benchmarks" / "benchmarks"
    
    if not benchmarks_root.exists():
        print(f"Error: Benchmarks directory does not exist: {benchmarks_root}", file=sys.stderr)
        parser.print_help()
        sys.exit(1)
    
    # Parse benchmark numbers if provided
    filter_numbers = None
    if args.benchmarks:
        filter_numbers = parse_benchmark_numbers(args.benchmarks)
        if not filter_numbers:
            print("Error: No valid benchmark numbers provided", file=sys.stderr)
            sys.exit(1)
    
    # Classify benchmarks
    tag_to_benchmarks, benchmark_to_tags, no_tags, total_count, tag_total_counts = classify_benchmarks(benchmarks_root, filter_numbers)
    
    # Print results
    print_classification(tag_to_benchmarks, benchmark_to_tags, no_tags, total_count, tag_total_counts, filter_numbers)


if __name__ == "__main__":
    main()

