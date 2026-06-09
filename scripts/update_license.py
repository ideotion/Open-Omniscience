#!/usr/bin/env python3
"""
Script to update all license references from MIT to GPLv3.
"""

import os
import re
from pathlib import Path

# GPLv3 header for Python files
GPL3_HEADER = '''"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com
"""

'''


def update_file_content(filepath):
    """Update file content to replace MIT with GPLv3."""
    with open(filepath, encoding="utf-8", errors="ignore") as f:
        content = f.read()

    original_content = content
    modified = False

    # Replace MIT license references
    replacements = [
        ('__license__ = "MIT"', '__license__ = "GPLv3"'),
        ("__license__ = 'MIT'", "__license__ = 'GPLv3'"),
        ("License: MIT", "License: GPLv3"),
        ("MIT License", "GNU General Public License v3"),
        ("license: MIT", "license: GPLv3"),
    ]

    for old, new in replacements:
        if old in content:
            content = content.replace(old, new)
            modified = True

    # Remove old MIT license text if present
    mit_license_pattern = r"Permission is hereby granted, free of charge.*?MIT License"
    if re.search(mit_license_pattern, content, re.IGNORECASE):
        # Find and remove MIT license block
        lines = content.split("\n")
        new_lines = []
        in_mit_block = False
        for line in lines:
            if "Permission is hereby granted" in line or "MIT License" in line:
                in_mit_block = True
            if in_mit_block:
                if line.strip() == "" and "Copyright" not in line:
                    in_mit_block = False
                    continue
            if not in_mit_block:
                new_lines.append(line)
        content = "\n".join(new_lines)
        modified = True

    # Add GPLv3 header if not present
    if "GNU General Public License" not in content:
        # Check if file has a shebang
        if content.lstrip().startswith("#!"):
            # Shell script - insert header after shebang
            lines = content.split("\n")
            lines.insert(1, "")
            lines.insert(
                2, "# Open Omniscience - Global Intelligence Platform for Investigative Journalism"
            )
            lines.insert(3, "#")
            lines.insert(4, "# Copyright (C) 2026 Ideotion")
            lines.insert(5, "#")
            lines.insert(
                6, "# This program is free software: you can redistribute it and/or modify"
            )
            lines.insert(
                7, "# it under the terms of the GNU General Public License as published by"
            )
            lines.insert(8, "# the Free Software Foundation, either version 3 of the License, or")
            lines.insert(9, "# (at your option) any later version.")
            lines.insert(10, "#")
            lines.insert(11, "# This program is distributed in the hope that it will be useful,")
            lines.insert(12, "# but WITHOUT ANY WARRANTY; without even the implied warranty of")
            lines.insert(13, "# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the")
            lines.insert(14, "# GNU General Public License for more details.")
            lines.insert(15, "#")
            lines.insert(16, "# You should have received a copy of the GNU General Public License")
            lines.insert(
                17, "# along with this program.  If not, see <http://www.gnu.org/licenses/>."
            )
            lines.insert(18, "#")
            lines.insert(19, "# For inquiries, contact: open-omniscience@ideotion.com")
            lines.insert(20, "")
            content = "\n".join(lines)
            modified = True
        elif content.lstrip().startswith('"""') or content.lstrip().startswith("'''"):
            # Python file with docstring - insert header before docstring
            lines = content.split("\n")
            insert_pos = 0
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith('"""') or stripped.startswith("'''"):
                    insert_pos = i
                    break
            if insert_pos > 0:
                header_lines = GPL3_HEADER.strip().split("\n")
                for j, header_line in enumerate(header_lines):
                    lines.insert(insert_pos + j, header_line)
                lines.insert(insert_pos + len(header_lines), "")
                content = "\n".join(lines)
                modified = True
        else:
            # Regular file - add header at top
            content = GPL3_HEADER + content
            modified = True

    # Only write if modified
    if content != original_content:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    return False


def process_directory(root_dir, extensions):
    """Process all files with given extensions."""
    count = 0
    for root, dirs, files in os.walk(root_dir):
        # Skip certain directories
        if ".git" in root or "__pycache__" in root or "archive" in root:
            continue
        for file in files:
            if any(file.endswith(ext) for ext in extensions):
                filepath = os.path.join(root, file)
                if update_file_content(filepath):
                    count += 1
                    print(f"  ✓ {filepath}")
    return count


def main():
    project_root = Path(__file__).parent.parent

    print("=" * 70)
    print("Updating License References to GPLv3")
    print("=" * 70)

    total = 0

    # Process Python files
    print("\nProcessing Python files...")
    total += process_directory(project_root, [".py"])

    # Process shell scripts
    print("\nProcessing shell scripts...")
    total += process_directory(project_root, [".sh"])

    # Process Makefile
    print("\nProcessing Makefile...")
    makefile_path = os.path.join(project_root, "Makefile")
    if os.path.exists(makefile_path):
        if update_file_content(makefile_path):
            total += 1
            print(f"  ✓ {makefile_path}")

    # Process YAML files
    print("\nProcessing YAML files...")
    total += process_directory(project_root, [".yml", ".yaml"])

    # Process other config files
    print("\nProcessing config files...")
    total += process_directory(project_root, [".txt", ".conf", ".ini"])

    print("\n" + "=" * 70)
    print(f"Total files updated: {total}")
    print("=" * 70)


if __name__ == "__main__":
    main()
