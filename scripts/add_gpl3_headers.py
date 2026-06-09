#!/usr/bin/env python3
"""
Script to add GPLv3 license headers to all Python files in the project.
"""

import os
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

# GPLv3 header for shell scripts
GPL3_SHELL_HEADER = """#!/bin/bash
# Open Omniscience - Global Intelligence Platform for Investigative Journalism
#
# Copyright (C) 2026 Ideotion
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# For inquiries, contact: open-omniscience@ideotion.com

"""

# GPLv3 header for Makefile
GPL3_MAKEFILE_HEADER = """# Open Omniscience - Global Intelligence Platform for Investigative Journalism
#
# Copyright (C) 2026 Ideotion
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# For inquiries, contact: open-omniscience@ideotion.com

"""

# GPLv3 header for YAML files
GPL3_YAML_HEADER = """# Open Omniscience - Global Intelligence Platform for Investigative Journalism
#
# Copyright (C) 2026 Ideotion
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# For inquiries, contact: open-omniscience@ideotion.com

"""


def has_gpl3_header(content, header):
    """Check if file already has GPLv3 header."""
    return "GNU General Public License" in content or "Open Omniscience" in content


def add_header_to_file(filepath, header):
    """Add GPLv3 header to a file."""
    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    # Check if file already has a header
    if has_gpl3_header(content, header):
        print(f"  ✓ {filepath} - Already has GPLv3 header")
        return False

    # Check if file has existing docstring/comment
    if (
        content.lstrip().startswith('"""')
        or content.lstrip().startswith("'''")
        or content.lstrip().startswith("#")
    ):
        # Find the end of the first line and insert header before it
        lines = content.split("\n")
        if lines[0].strip() == "":
            # Empty first line, insert after it
            lines.insert(1, header.rstrip("\n"))
        else:
            # Insert before first line
            lines.insert(0, header.rstrip("\n"))
        new_content = "\n".join(lines)
    else:
        # No existing header, add at the top
        new_content = header + content

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"  ✓ {filepath} - Added GPLv3 header")
    return True


def process_python_files(root_dir):
    """Process all Python files."""
    print("\nProcessing Python files...")
    count = 0
    for root, dirs, files in os.walk(root_dir):
        # Skip certain directories
        if ".git" in root or "__pycache__" in root or "archive" in root:
            continue
        for file in files:
            if file.endswith(".py"):
                filepath = os.path.join(root, file)
                if add_header_to_file(filepath, GPL3_HEADER):
                    count += 1
    print(f"  Total Python files updated: {count}")
    return count


def process_shell_scripts(root_dir):
    """Process all shell script files."""
    print("\nProcessing shell scripts...")
    count = 0
    for root, dirs, files in os.walk(root_dir):
        if ".git" in root or "archive" in root:
            continue
        for file in files:
            if file.endswith(".sh") and not file.startswith("."):
                filepath = os.path.join(root, file)
                if add_header_to_file(filepath, GPL3_SHELL_HEADER):
                    count += 1
    print(f"  Total shell scripts updated: {count}")
    return count


def process_makefiles(root_dir):
    """Process Makefile."""
    print("\nProcessing Makefile...")
    count = 0
    makefile_path = os.path.join(root_dir, "Makefile")
    if os.path.exists(makefile_path):
        if add_header_to_file(makefile_path, GPL3_MAKEFILE_HEADER):
            count += 1
    print(f"  Total Makefiles updated: {count}")
    return count


def process_yaml_files(root_dir):
    """Process YAML files."""
    print("\nProcessing YAML files...")
    count = 0
    yaml_extensions = [".yml", ".yaml"]
    for root, dirs, files in os.walk(root_dir):
        if ".git" in root or "archive" in root:
            continue
        for file in files:
            if any(file.lower().endswith(ext) for ext in yaml_extensions):
                filepath = os.path.join(root, file)
                if add_header_to_file(filepath, GPL3_YAML_HEADER):
                    count += 1
    print(f"  Total YAML files updated: {count}")
    return count


def main():
    project_root = Path(__file__).parent.parent

    print("=" * 70)
    print("Adding GPLv3 Headers to Open Omniscience Project")
    print("=" * 70)

    total = 0
    total += process_python_files(project_root)
    total += process_shell_scripts(project_root)
    total += process_makefiles(project_root)
    total += process_yaml_files(project_root)

    print("\n" + "=" * 70)
    print(f"Total files updated with GPLv3 headers: {total}")
    print("=" * 70)


if __name__ == "__main__":
    main()
