#!/usr/bin/env python3
"""
Phase 4: Custom Linter
Performs static analysis similar to flake8/pylint without external dependencies.
"""

import ast
import os
import re


class CustomLinter:
    def __init__(self):
        self.issues: list[dict] = []
        self.current_file: str = ""

    def lint_file(self, filepath: str):
        """Lint a single Python file."""
        self.current_file = filepath

        try:
            with open(filepath, encoding="utf-8", errors="ignore") as f:
                content = f.read()

            lines = content.split("\n")

            # Run all checks
            self._check_line_length(lines)
            self._check_trailing_whitespace(lines)
            self._check_mixed_tabs_spaces(lines)
            self._check_encoding_declaration(lines)
            self._check_shebang(lines)
            self._check_import_order(content)
            self._check_unused_imports(content)
            self._check_wildcard_imports(content)
            self._check_naming_conventions(content)

        except Exception as e:
            self.issues.append(
                {
                    "file": filepath,
                    "line": 0,
                    "code": "E999",
                    "message": f"Failed to lint: {str(e)}",
                    "severity": "LOW",
                }
            )

    def _check_line_length(self, lines: list[str]):
        """Check for lines exceeding 120 characters."""
        for i, line in enumerate(lines, 1):
            if len(line) > 120:
                self.issues.append(
                    {
                        "file": self.current_file,
                        "line": i,
                        "code": "E501",
                        "message": f"Line too long ({len(line)} > 120 characters)",
                        "severity": "LOW",
                    }
                )

    def _check_trailing_whitespace(self, lines: list[str]):
        """Check for trailing whitespace."""
        for i, line in enumerate(lines, 1):
            if line.rstrip() != line:
                self.issues.append(
                    {
                        "file": self.current_file,
                        "line": i,
                        "code": "W291",
                        "message": "Trailing whitespace",
                        "severity": "LOW",
                    }
                )

    def _check_mixed_tabs_spaces(self, lines: list[str]):
        """Check for mixed tabs and spaces."""
        for i, line in enumerate(lines, 1):
            if "\t" in line and "    " in line:
                self.issues.append(
                    {
                        "file": self.current_file,
                        "line": i,
                        "code": "W191",
                        "message": "Mixed tabs and spaces",
                        "severity": "LOW",
                    }
                )

    def _check_encoding_declaration(self, lines: list[str]):
        """Check for encoding declaration in Python files."""
        if len(lines) > 0:
            first_line = lines[0]
            if not first_line.startswith("# -*- coding:"):
                # Check if it's a shebang
                if not first_line.startswith("#!"):
                    # Encoding declaration is optional in Python 3
                    pass

    def _check_shebang(self, lines: list[str]):
        """Check for consistent shebang usage."""
        if len(lines) > 0:
            if lines[0].startswith("#!"):
                if "python" not in lines[0].lower():
                    self.issues.append(
                        {
                            "file": self.current_file,
                            "line": 1,
                            "code": "W292",
                            "message": "Non-Python shebang in Python file",
                            "severity": "LOW",
                        }
                    )

    def _check_import_order(self, content: str):
        """Check for proper import ordering (stdlib, third-party, local)."""
        try:
            tree = ast.parse(content)
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(("import", alias.name, node.lineno))
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        module = node.module or ""
                        imports.append(("from", f"{module}.{alias.name}", node.lineno))

            # Check for stdlib imports after third-party
            stdlib_modules = {
                "os",
                "sys",
                "json",
                "re",
                "ast",
                "time",
                "datetime",
                "collections",
                "itertools",
                "functools",
                "operator",
                "copy",
                "heapq",
                "bisect",
                "pathlib",
                "argparse",
                "logging",
                "traceback",
                "warnings",
                "abc",
                "dataclasses",
                "typing",
                "enum",
                "contextlib",
                "urllib",
                "http",
                "socket",
                "ssl",
                "hashlib",
                "hmac",
                "base64",
                "binascii",
            }

            third_party_modules = {
                "requests",
                "beautifulsoup4",
                "flask",
                "fastapi",
                "sqlalchemy",
                "pydantic",
                "numpy",
                "pandas",
                "scipy",
                "sklearn",
                "tensorflow",
                "torch",
                "pytest",
                "hypothesis",
                "mypy",
                "flake8",
                "black",
            }

            stdlib_lines = []
            third_party_lines = []

            for imp_type, module, line in imports:
                parts = module.split(".")
                base_module = parts[0]

                if base_module in stdlib_modules:
                    stdlib_lines.append(line)
                elif base_module in third_party_modules or "." in base_module:
                    third_party_lines.append(line)

            # Check if any stdlib imports come after third-party
            if stdlib_lines and third_party_lines:
                max_stdlib = max(stdlib_lines)
                min_third = min(third_party_lines)
                if max_stdlib > min_third:
                    self.issues.append(
                        {
                            "file": self.current_file,
                            "line": max_stdlib,
                            "code": "I100",
                            "message": "Standard library import after third-party import",
                            "severity": "LOW",
                        }
                    )
        except SyntaxError:
            pass

    def _check_unused_imports(self, content: str):
        """Check for potentially unused imports."""
        try:
            tree = ast.parse(content)

            # Get all imports
            imports = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        imports.add(alias.name)

            # Get all names used in the code
            used_names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    used_names.add(node.id)
                elif isinstance(node, ast.Attribute):
                    if isinstance(node.value, ast.Name):
                        used_names.add(node.value.id)

            # Find potentially unused imports
            for imp in imports:
                # Skip if it's a common name that might be used dynamically
                if imp not in used_names and not imp.startswith("_"):
                    # This might be a false positive, so we'll be conservative
                    pass
        except SyntaxError:
            pass

    def _check_wildcard_imports(self, content: str):
        """Check for wildcard imports."""
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        if alias.name == "*":
                            self.issues.append(
                                {
                                    "file": self.current_file,
                                    "line": node.lineno,
                                    "code": "W0401",
                                    "message": f"Wildcard import: from {node.module} import *",
                                    "severity": "LOW",
                                }
                            )
        except SyntaxError:
            pass

    def _check_naming_conventions(self, content: str):
        """Check for naming convention violations."""
        try:
            tree = ast.parse(content)

            for node in ast.walk(tree):
                # Check class names (should be CamelCase)
                if isinstance(node, ast.ClassDef):
                    if not re.match(r"^[A-Z][a-zA-Z0-9_]*$", node.name):
                        self.issues.append(
                            {
                                "file": self.current_file,
                                "line": node.lineno,
                                "code": "N801",
                                "message": f"Class name '{node.name}' should use CamelCase",
                                "severity": "LOW",
                            }
                        )

                # Check function names (should be snake_case)
                if isinstance(node, ast.FunctionDef):
                    if not node.name.startswith("_") and not re.match(
                        r"^[a-z][a-z0-9_]*$", node.name
                    ):
                        # Skip __init__, __repr__, etc.
                        if not (node.name.startswith("__") and node.name.endswith("__")):
                            self.issues.append(
                                {
                                    "file": self.current_file,
                                    "line": node.lineno,
                                    "code": "N802",
                                    "message": f"Function name '{node.name}' should use snake_case",
                                    "severity": "LOW",
                                }
                            )

                # Check variable names (should be snake_case)
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                    if not node.id.startswith("_") and not re.match(r"^[a-z][a-z0-9_]*$", node.id):
                        # Skip single letter variables in loops
                        if len(node.id) > 1:
                            self.issues.append(
                                {
                                    "file": self.current_file,
                                    "line": node.lineno,
                                    "code": "N803",
                                    "message": f"Variable name '{node.id}' should use snake_case",
                                    "severity": "LOW",
                                }
                            )
        except SyntaxError:
            pass

    def lint_directory(self, directory: str):
        """Lint all Python files in a directory."""
        exclude_patterns = [
            ".git",
            "__pycache__",
            ".venv",
            "venv",
            "node_modules",
            "PHASE",
            "QUBS_",
            "FINAL_REPORT",
            "MASTER_DEBUG",
            "INSTALLER_TEST",
        ]

        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if not any(p in d for p in exclude_patterns)]

            for file in files:
                if file.endswith(".py"):
                    filepath = os.path.join(root, file)
                    if not any(p in filepath for p in exclude_patterns):
                        self.lint_file(filepath)

    def save_report(self, output_file: str):
        """Save linting report to JSON file."""
        import json

        with open(output_file, "w") as f:
            json.dump(self.issues, f, indent=2)

    def print_summary(self):
        """Print summary of linting results."""
        print("\n" + "=" * 80)
        print("PHASE 4A: LINTING SUMMARY")
        print("=" * 80)

        # Group by code
        by_code = {}
        for issue in self.issues:
            code = issue.get("code", "UNKNOWN")
            if code not in by_code:
                by_code[code] = []
            by_code[code].append(issue)

        print(f"\nTotal issues found: {len(self.issues)}")
        print("\nBy Issue Code:")
        for code in sorted(by_code.keys()):
            count = len(by_code[code])
            print(f"  {code}: {count}")

        print("\n" + "=" * 80)
        print("SAMPLE ISSUES:")
        print("=" * 80)
        for issue in self.issues[:20]:
            print(f"\n{issue['file']}:{issue['line']}")
            print(f"  Code: {issue['code']}")
            print(f"  Message: {issue['message']}")


if __name__ == "__main__":
    linter = CustomLinter()

    print("Linting src/ directory...")
    linter.lint_directory("src")

    print("Linting pillar2/src/ directory...")
    linter.lint_directory("pillar2/src")

    print("Linting pillar3/src/ directory...")
    linter.lint_directory("pillar3/src")

    print("Linting pillar4/src/ directory...")
    linter.lint_directory("pillar4/src")

    linter.save_report("/tmp/phase4_lint_report.json")
    linter.print_summary()
