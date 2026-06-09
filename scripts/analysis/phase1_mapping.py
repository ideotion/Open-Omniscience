#!/usr/bin/env python3
"""
Phase 1: Recursive Codebase Mapping
Generates a comprehensive inventory of all files and directories in the repository.
"""

import hashlib
import json
import os
from datetime import datetime

REPO_ROOT = "/workspace/ideotion__Open-Omniscience"
OUTPUT_FILE = "/workspace/ideotion__Open-Omniscience/PHASE1_REPORT.json"


def get_file_info(filepath):
    """Get comprehensive file information."""
    stat = os.stat(filepath)

    # Calculate SHA256 hash
    sha256_hash = ""
    try:
        with open(filepath, "rb") as f:
            file_hash = hashlib.sha256()
            while chunk := f.read(8192):
                file_hash.update(chunk)
            sha256_hash = file_hash.hexdigest()
    except OSError:
        sha256_hash = "N/A"

    # Determine file type
    if filepath.endswith(".py"):
        file_type = "Python Source"
    elif filepath.endswith(".md"):
        file_type = "Markdown"
    elif filepath.endswith(".txt"):
        file_type = "Text"
    elif filepath.endswith(".yml") or filepath.endswith(".yaml"):
        file_type = "YAML"
    elif filepath.endswith(".json"):
        file_type = "JSON"
    elif filepath.endswith(".sh"):
        file_type = "Shell Script"
    elif filepath.endswith(".conf") or filepath.endswith(".cfg"):
        file_type = "Configuration"
    elif filepath.endswith(".ini"):
        file_type = "INI Configuration"
    elif filepath.endswith(".toml"):
        file_type = "TOML"
    elif filepath.endswith(".svg"):
        file_type = "SVG Image"
    elif os.path.islink(filepath):
        file_type = "Symbolic Link"
    elif os.access(filepath, os.X_OK):
        file_type = "Executable"
    else:
        file_type = "Other"

    return {
        "path": filepath,
        "relative_path": os.path.relpath(filepath, REPO_ROOT),
        "size_bytes": stat.st_size,
        "size_human": format_size(stat.st_size),
        "modified_timestamp": stat.st_mtime,
        "modified_date": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "mode": oct(stat.st_mode),
        "mode_human": file_mode_to_human(stat.st_mode),
        "sha256": sha256_hash,
        "file_type": file_type,
        "extension": os.path.splitext(filepath)[1] if os.path.splitext(filepath)[1] else "none",
    }


def get_dir_info(dirpath):
    """Get directory information."""
    stat = os.stat(dirpath)

    # Count contents
    file_count = 0
    dir_count = 0
    total_size = 0

    for root, dirs, files in os.walk(dirpath):
        dir_count += len(dirs)
        file_count += len(files)
        for f in files:
            fpath = os.path.join(root, f)
            try:
                total_size += os.path.getsize(fpath)
            except OSError:
                pass

    return {
        "path": dirpath,
        "relative_path": os.path.relpath(dirpath, REPO_ROOT),
        "size_bytes": total_size,
        "size_human": format_size(total_size),
        "modified_timestamp": stat.st_mtime,
        "modified_date": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "mode": oct(stat.st_mode),
        "mode_human": file_mode_to_human(stat.st_mode),
        "file_count": file_count,
        "dir_count": dir_count,
        "total_items": file_count + dir_count,
        "type": "directory",
    }


def format_size(size_bytes):
    """Format size in human-readable format."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def file_mode_to_human(mode):
    """Convert file mode to human-readable string."""
    mode_str = ""
    if mode & 0o400:
        mode_str += "r"
    else:
        mode_str += "-"
    if mode & 0o200:
        mode_str += "w"
    else:
        mode_str += "-"
    if mode & 0o100:
        mode_str += "x"
    else:
        mode_str += "-"
    if mode & 0o040:
        mode_str += "r"
    else:
        mode_str += "-"
    if mode & 0o020:
        mode_str += "w"
    else:
        mode_str += "-"
    if mode & 0o010:
        mode_str += "x"
    else:
        mode_str += "-"
    if mode & 0o004:
        mode_str += "r"
    else:
        mode_str += "-"
    if mode & 0o002:
        mode_str += "w"
    else:
        mode_str += "-"
    if mode & 0o001:
        mode_str += "x"
    else:
        mode_str += "-"
    return mode_str


def main():
    """Main mapping function."""
    print("Starting Phase 1: Recursive Codebase Mapping...")
    print(f"Repository Root: {REPO_ROOT}")

    inventory = {
        "repository": {
            "name": "Open-Omniscience",
            "url": "https://github.com/ideotion/Open-Omniscience",
            "local_path": REPO_ROOT,
            "scan_timestamp": datetime.now().isoformat(),
            "scan_type": "Phase 1: Recursive Codebase Mapping",
        },
        "summary": {},
        "directories": [],
        "files": [],
        "structure": {},
    }

    # Walk through the repository
    for root, dirs, files in os.walk(REPO_ROOT):
        # Skip .git directory
        if ".git" in root:
            continue

        # Process directories
        for dirname in dirs:
            dirpath = os.path.join(root, dirname)
            if ".git" not in dirpath:
                dir_info = get_dir_info(dirpath)
                inventory["directories"].append(dir_info)

        # Process files
        for filename in files:
            filepath = os.path.join(root, filename)
            if ".git" not in filepath:
                file_info = get_file_info(filepath)
                inventory["files"].append(file_info)

    # Sort for consistent output
    inventory["directories"].sort(key=lambda x: x["path"])
    inventory["files"].sort(key=lambda x: x["path"])

    # Generate summary statistics
    total_files = len(inventory["files"])
    total_dirs = len(inventory["directories"])
    total_size = sum(f["size_bytes"] for f in inventory["files"])

    # Count by file type
    type_counts = {}
    for f in inventory["files"]:
        ftype = f["file_type"]
        type_counts[ftype] = type_counts.get(ftype, 0) + 1

    # Count by extension
    ext_counts = {}
    for f in inventory["files"]:
        ext = f["extension"]
        ext_counts[ext] = ext_counts.get(ext, 0) + 1

    # Largest files
    largest_files = sorted(inventory["files"], key=lambda x: x["size_bytes"], reverse=True)[:20]

    inventory["summary"] = {
        "total_files": total_files,
        "total_directories": total_dirs,
        "total_size_bytes": total_size,
        "total_size_human": format_size(total_size),
        "file_type_distribution": type_counts,
        "extension_distribution": ext_counts,
        "largest_files": [
            {
                "path": f["relative_path"],
                "size": f["size_human"],
                "size_bytes": f["size_bytes"],
                "type": f["file_type"],
            }
            for f in largest_files
        ],
        "scan_completed": datetime.now().isoformat(),
    }

    # Build hierarchical structure
    inventory["structure"] = build_hierarchy(REPO_ROOT)

    # Save to JSON
    with open(OUTPUT_FILE, "w") as f:
        json.dump(inventory, f, indent=2, default=str)

    print("\nPhase 1 Complete!")
    print(f"Total Files: {total_files}")
    print(f"Total Directories: {total_dirs}")
    print(f"Total Size: {format_size(total_size)}")
    print(f"Report saved to: {OUTPUT_FILE}")

    # Print summary
    print("\n=== File Type Distribution ===")
    for ftype, count in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {ftype}: {count}")

    print("\n=== Top 10 Largest Files ===")
    for i, f in enumerate(largest_files[:10], 1):
        print(f"  {i}. {f['relative_path']} ({f['size_human']})")


def build_hierarchy(root_path):
    """Build a hierarchical structure of the repository."""
    hierarchy = {}

    for root, dirs, files in os.walk(root_path):
        if ".git" in root:
            continue

        rel_path = os.path.relpath(root, root_path)
        if rel_path == ".":
            rel_path = ""

        current_level = hierarchy
        if rel_path:
            parts = rel_path.split(os.sep)
            for part in parts:
                if part not in current_level:
                    current_level[part] = {}
                current_level = current_level[part]

        # Add files
        for filename in files:
            if filename not in current_level:
                current_level[filename] = None  # Mark as file

        # Add directories (will be populated by walk)
        for dirname in dirs:
            if dirname not in current_level:
                current_level[dirname] = {}

    return hierarchy


if __name__ == "__main__":
    main()
