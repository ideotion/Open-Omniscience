#!/usr/bin/env python3
"""
Phase 2: Simple Reference Verifier
Verifies file paths and imports without network checks.
"""

import json
import os


class SimpleVerifier:
    def __init__(self, root_dir: str = "."):
        self.root_dir = root_dir
        self.all_files: set[str] = set()
        self.issues: list[dict] = []

        # Collect all files
        self._collect_all_files()

    def _collect_all_files(self):
        """Collect all file paths in the repository."""
        exclude_patterns = [
            ".git",
            "__pycache__",
            ".venv",
            "venv",
            "node_modules",
        ]

        for root, dirs, files in os.walk(self.root_dir):
            # Filter out excluded directories
            dirs[:] = [d for d in dirs if not any(p in d for p in exclude_patterns)]

            for file in files:
                filepath = os.path.normpath(os.path.join(root, file))
                self.all_files.add(filepath)

    def _normalize_path(self, path: str, source_file: str = None) -> str:
        """Normalize a path relative to source file or repo root."""
        if path.startswith("/"):
            return path

        if source_file:
            source_dir = os.path.dirname(source_file)
            return os.path.normpath(os.path.join(source_dir, path))

        return os.path.normpath(os.path.join(self.root_dir, path))

    def _file_exists(self, path: str) -> bool:
        """Check if a file exists."""
        if path in self.all_files:
            return True

        # Try case-insensitive check
        path_lower = path.lower()
        for f in self.all_files:
            if f.lower() == path_lower:
                return True

        # Check if file exists on disk
        if os.path.isfile(path):
            return True

        return False

    def verify_file_paths(self):
        """Verify all file path references."""
        print("Scanning for file path references...")

        # Common file extensions to check
        extensions = [".py", ".sh", ".md", ".html", ".js", ".css", ".json", ".yaml", ".yml"]

        for root, dirs, files in os.walk(self.root_dir):
            dirs[:] = [
                d
                for d in dirs
                if not any(p in d for p in [".git", "__pycache__", ".venv", "venv", "node_modules"])
            ]

            for file in files:
                filepath = os.path.join(root, file)
                ext = os.path.splitext(file)[1].lower()

                if ext not in extensions:
                    continue

                try:
                    with open(filepath, encoding="utf-8", errors="ignore") as f:
                        content = f.read()

                    # Find all string literals that look like file paths
                    import re

                    # Pattern for file paths in strings
                    file_pattern = r'["\'](?:\.\.?/)?[^"\'\s]+\.(?:py|sh|md|html|js|css|json|yaml|yml|txt|conf|config)["\']'

                    for match in re.finditer(file_pattern, content):
                        path_ref = match.group(0).strip("\"'")

                        # Skip if it's a URL
                        if path_ref.startswith("http"):
                            continue

                        # Normalize path
                        normalized = self._normalize_path(path_ref, filepath)

                        # Check if file exists
                        if not self._file_exists(normalized):
                            # Try relative to repo root
                            normalized_root = self._normalize_path(path_ref, self.root_dir)
                            if not self._file_exists(normalized_root):
                                self.issues.append(
                                    {
                                        "file": filepath,
                                        "category": "file_path",
                                        "reference": path_ref,
                                        "normalized": normalized,
                                        "status": "MISSING",
                                        "message": f"File '{path_ref}' not found",
                                        "severity": "CRITICAL",
                                    }
                                )

                    # Check for open() calls in Python
                    if ext == ".py":
                        open_pattern = r'open\(["\']([^"\']+)["\']'
                        for match in re.finditer(open_pattern, content):
                            path_ref = match.group(1)
                            if not path_ref.startswith("/") and not path_ref.startswith("http"):
                                normalized = self._normalize_path(path_ref, filepath)
                                if not self._file_exists(normalized):
                                    self.issues.append(
                                        {
                                            "file": filepath,
                                            "category": "file_path",
                                            "reference": path_ref,
                                            "normalized": normalized,
                                            "status": "MISSING",
                                            "message": f"File in open() '{path_ref}' not found",
                                            "severity": "CRITICAL",
                                        }
                                    )

                    # Check for source commands in shell scripts
                    if ext == ".sh":
                        source_pattern = r"source\s+([^\s;]+)"
                        for match in re.finditer(source_pattern, content):
                            path_ref = match.group(1)
                            normalized = self._normalize_path(path_ref, filepath)
                            if not self._file_exists(normalized):
                                self.issues.append(
                                    {
                                        "file": filepath,
                                        "category": "file_path",
                                        "reference": path_ref,
                                        "normalized": normalized,
                                        "status": "MISSING",
                                        "message": f"Source file '{path_ref}' not found",
                                        "severity": "CRITICAL",
                                    }
                                )

                    # Check Markdown links
                    if ext == ".md":
                        link_pattern = r"\[([^\]]+)\]\(([^\)]+)\)"
                        for match in re.finditer(link_pattern, content):
                            text, url = match.groups()
                            if not url.startswith("http"):
                                normalized = self._normalize_path(url, filepath)
                                if not self._file_exists(normalized):
                                    self.issues.append(
                                        {
                                            "file": filepath,
                                            "category": "file_path",
                                            "reference": url,
                                            "normalized": normalized,
                                            "status": "MISSING",
                                            "message": f"Markdown link '{url}' not found",
                                            "severity": "MEDIUM",
                                        }
                                    )

                except Exception as e:
                    print(f"Error processing {filepath}: {e}")

    def verify_imports(self):
        """Verify Python imports."""
        print("Scanning for Python import references...")

        for root, dirs, files in os.walk(self.root_dir):
            dirs[:] = [
                d
                for d in dirs
                if not any(p in d for p in [".git", "__pycache__", ".venv", "venv", "node_modules"])
            ]

            for file in files:
                if not file.endswith(".py"):
                    continue

                filepath = os.path.join(root, file)

                try:
                    with open(filepath, encoding="utf-8", errors="ignore") as f:
                        content = f.read()

                    import re

                    # Standard imports
                    import_pattern = r"^\s*import\s+([a-zA-Z0-9_.,\s]+)"
                    for match in re.finditer(import_pattern, content, re.MULTILINE):
                        modules = match.group(1).replace(" ", "").split(",")
                        for module in modules:
                            module = module.strip()
                            if not module:
                                continue

                            # Skip if it's a multi-line artifact
                            if "\n" in module or "import" in module:
                                continue

                            # Check if it's a local file reference
                            if module.endswith(".py") or "/" in module or module.startswith("."):
                                normalized = self._normalize_path(module, filepath)
                                if not self._file_exists(normalized):
                                    self.issues.append(
                                        {
                                            "file": filepath,
                                            "category": "python_import",
                                            "reference": module,
                                            "status": "MISSING",
                                            "message": f"Import '{module}' not found as file",
                                            "severity": "HIGH",
                                        }
                                    )

                    # From imports
                    from_pattern = r"^\s*from\s+([a-zA-Z0-9_.]+)\s+import\s+([a-zA-Z0-9_.,\s*]+)"
                    for match in re.finditer(from_pattern, content, re.MULTILINE):
                        module = match.group(1)
                        items = match.group(2).replace(" ", "").split(",")

                        # Check if module is a local file
                        if module.endswith(".py") or "/" in module or module.startswith("."):
                            normalized = self._normalize_path(module, filepath)
                            if not self._file_exists(normalized):
                                self.issues.append(
                                    {
                                        "file": filepath,
                                        "category": "python_from_import",
                                        "reference": module,
                                        "status": "MISSING",
                                        "message": f"From import '{module}' not found as file",
                                        "severity": "HIGH",
                                    }
                                )

                except Exception as e:
                    print(f"Error processing {filepath}: {e}")

    def save_issues(self, output_file: str):
        """Save verification issues to JSON file."""
        with open(output_file, "w") as f:
            json.dump(self.issues, f, indent=2)

    def print_summary(self):
        """Print summary of verification results."""
        print("\n" + "=" * 80)
        print("PHASE 2 VERIFICATION SUMMARY")
        print("=" * 80)

        # Group by severity
        by_severity = {"CRITICAL": [], "HIGH": [], "MEDIUM": [], "LOW": []}
        for issue in self.issues:
            severity = issue.get("severity", "LOW")
            by_severity[severity].append(issue)

        print(f"\nTotal issues found: {len(self.issues)}")
        for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            count = len(by_severity[severity])
            print(f"  {severity}: {count}")

        print("\n" + "=" * 80)
        print("CRITICAL ISSUES (Missing Files)")
        print("=" * 80)
        for issue in by_severity["CRITICAL"][:50]:
            print(f"\n  File: {issue['file']}")
            print(f"    Reference: {issue['reference']}")
            print(f"    Message: {issue['message']}")

        if len(by_severity["CRITICAL"]) > 50:
            print(f"\n  ... and {len(by_severity['CRITICAL']) - 50} more")

        print("\n" + "=" * 80)
        print("HIGH ISSUES (Missing Imports)")
        print("=" * 80)
        for issue in by_severity["HIGH"][:20]:
            print(f"\n  File: {issue['file']}")
            print(f"    Reference: {issue['reference']}")
            print(f"    Message: {issue['message']}")

        if len(by_severity["HIGH"]) > 20:
            print(f"\n  ... and {len(by_severity['HIGH']) - 20} more")


if __name__ == "__main__":
    verifier = SimpleVerifier()
    verifier.verify_file_paths()
    verifier.verify_imports()
    verifier.save_issues("/tmp/phase2_simple_issues.json")
    verifier.print_summary()
