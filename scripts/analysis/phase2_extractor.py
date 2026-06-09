#!/usr/bin/env python3
"""
Phase 2: Reference Extractor
Extracts all references from all files in the repository.
"""

import json
import os
import re


class ReferenceExtractor:
    def __init__(self, root_dir: str = "."):
        self.root_dir = root_dir
        self.all_references: dict[str, dict[str, list[str]]] = {}
        self.file_types = {
            ".py": self._extract_python_refs,
            ".sh": self._extract_shell_refs,
            ".js": self._extract_js_refs,
            ".md": self._extract_markdown_refs,
            ".html": self._extract_html_refs,
            ".css": self._extract_css_refs,
            ".json": self._extract_json_refs,
            ".yml": self._extract_yaml_refs,
            ".yaml": self._extract_yaml_refs,
            ".txt": self._extract_text_refs,
            ".conf": self._extract_config_refs,
            ".config": self._extract_config_refs,
            "Makefile": self._extract_makefile_refs,
        }

    def _normalize_path(self, path: str) -> str:
        """Normalize path to absolute from repo root."""
        if path.startswith("/"):
            return path
        return os.path.normpath(os.path.join(self.root_dir, path))

    def _extract_python_refs(self, content: str, filepath: str) -> dict[str, list[str]]:
        """Extract Python-specific references."""
        refs = {
            "imports": [],
            "from_imports": [],
            "file_paths": [],
            "env_vars": [],
            "urls": [],
        }

        # Standard imports: import X
        import_pattern = r"^\s*import\s+([a-zA-Z0-9_.,\s]+)"
        for match in re.finditer(import_pattern, content, re.MULTILINE):
            modules = match.group(1).replace(" ", "").split(",")
            refs["imports"].extend(modules)

        # From imports: from X import Y
        from_pattern = r"^\s*from\s+([a-zA-Z0-9_.]+)\s+import\s+([a-zA-Z0-9_.,\s*]+)"
        for match in re.finditer(from_pattern, content, re.MULTILINE):
            module = match.group(1)
            items = match.group(2).replace(" ", "").split(",")
            refs["from_imports"].append(f"{module} -> {', '.join(items)}")

        # File paths (open(), with open(), etc.)
        file_pattern = (
            r'["\'](?:\.\.?/)?[^"\']+\.(?:py|json|yaml|yml|txt|md|html|css|js|sh|conf|config)["\']'
        )
        for match in re.finditer(file_pattern, content):
            refs["file_paths"].append(match.group(0).strip("\"'"))

        # open() calls
        open_pattern = r'open\(["\']([^"\']+)["\']'
        for match in re.finditer(open_pattern, content):
            refs["file_paths"].append(match.group(1))

        # Environment variables
        env_pattern = r'os\.environ\[?["\']?([A-Z_][A-Z0-9_]*)["\']?\]?'
        for match in re.finditer(env_pattern, content):
            refs["env_vars"].append(match.group(1))

        # URLs
        url_pattern = r'https?://[^\s"\']+'
        for match in re.finditer(url_pattern, content):
            refs["urls"].append(match.group(0))

        return refs

    def _extract_shell_refs(self, content: str, filepath: str) -> dict[str, list[str]]:
        """Extract shell script references."""
        refs = {
            "commands": [],
            "file_paths": [],
            "env_vars": [],
            "urls": [],
        }

        # Source commands
        source_pattern = r"source\s+([^\s;]+)"
        for match in re.finditer(source_pattern, content):
            refs["file_paths"].append(match.group(1))

        # File paths
        file_pattern = r'["\']\.?[^"\']+\.(?:sh|py|json|yaml|yml|txt|md|conf|config)["\']'
        for match in re.finditer(file_pattern, content):
            refs["file_paths"].append(match.group(0).strip("\"'"))

        # Environment variables
        env_pattern = r"\$([A-Z_][A-Z0-9_]*)"
        for match in re.finditer(env_pattern, content):
            refs["env_vars"].append(match.group(1))

        # URLs
        url_pattern = r'https?://[^\s"\']+'
        for match in re.finditer(url_pattern, content):
            refs["urls"].append(match.group(0))

        return refs

    def _extract_js_refs(self, content: str, filepath: str) -> dict[str, list[str]]:
        """Extract JavaScript references."""
        refs = {
            "imports": [],
            "requires": [],
            "file_paths": [],
            "urls": [],
        }

        # ES6 imports
        import_pattern = r'from\s+["\']([^"\']+)["\']'
        for match in re.finditer(import_pattern, content):
            refs["imports"].append(match.group(1))

        # require() calls
        require_pattern = r'require\(["\']([^"\']+)["\']\)'
        for match in re.finditer(require_pattern, content):
            refs["requires"].append(match.group(1))

        # File paths
        file_pattern = r'["\'](?:\.\.?/)?[^"\']+\.(?:js|json|css|html|md)["\']'
        for match in re.finditer(file_pattern, content):
            refs["file_paths"].append(match.group(0).strip("\"'"))

        # URLs
        url_pattern = r'https?://[^\s"\']+'
        for match in re.finditer(url_pattern, content):
            refs["urls"].append(match.group(0))

        return refs

    def _extract_markdown_refs(self, content: str, filepath: str) -> dict[str, list[str]]:
        """Extract Markdown references."""
        refs = {
            "links": [],
            "images": [],
            "file_refs": [],
        }

        # Links: [text](url)
        link_pattern = r"\[([^\]]+)\]\(([^\)]+)\)"
        for match in re.finditer(link_pattern, content):
            text, url = match.groups()
            if url.startswith("http"):
                refs["links"].append(url)
            else:
                refs["file_refs"].append(url)

        # Images: ![alt](url)
        image_pattern = r"!\[([^\]]+)\]\(([^\)]+)\)"
        for match in re.finditer(image_pattern, content):
            alt, url = match.groups()
            if url.startswith("http"):
                refs["images"].append(url)
            else:
                refs["file_refs"].append(url)

        return refs

    def _extract_html_refs(self, content: str, filepath: str) -> dict[str, list[str]]:
        """Extract HTML references."""
        refs = {
            "scripts": [],
            "stylesheets": [],
            "links": [],
            "images": [],
        }

        # Script tags
        script_pattern = r'<script[^>]*src=["\']([^"\']+)["\']'
        for match in re.finditer(script_pattern, content):
            refs["scripts"].append(match.group(1))

        # Stylesheet tags
        style_pattern = r'<link[^>]*href=["\']([^"\']+)["\']'
        for match in re.finditer(style_pattern, content):
            refs["stylesheets"].append(match.group(1))

        # Anchor tags
        link_pattern = r'<a[^>]*href=["\']([^"\']+)["\']'
        for match in re.finditer(link_pattern, content):
            refs["links"].append(match.group(1))

        # Image tags
        image_pattern = r'<img[^>]*src=["\']([^"\']+)["\']'
        for match in re.finditer(image_pattern, content):
            refs["images"].append(match.group(1))

        return refs

    def _extract_css_refs(self, content: str, filepath: str) -> dict[str, list[str]]:
        """Extract CSS references."""
        refs = {
            "imports": [],
            "urls": [],
        }

        # @import rules
        import_pattern = r'@import\s+["\']([^"\']+)["\']'
        for match in re.finditer(import_pattern, content):
            refs["imports"].append(match.group(1))

        # url() references
        url_pattern = r'url\(["\']?([^"\']+)["\']?\)'
        for match in re.finditer(url_pattern, content):
            refs["urls"].append(match.group(1))

        return refs

    def _extract_json_refs(self, content: str, filepath: str) -> dict[str, list[str]]:
        """Extract JSON references."""
        refs = {
            "file_paths": [],
            "urls": [],
        }

        # File paths in values
        file_pattern = r'["\'](?:\.\.?/)?[^"\']+\.(?:json|yaml|yml|txt|md)["\']'
        for match in re.finditer(file_pattern, content):
            refs["file_paths"].append(match.group(0).strip("\"'"))

        # URLs
        url_pattern = r'https?://[^\s"\']+'
        for match in re.finditer(url_pattern, content):
            refs["urls"].append(match.group(0))

        return refs

    def _extract_yaml_refs(self, content: str, filepath: str) -> dict[str, list[str]]:
        """Extract YAML references."""
        refs = {
            "file_paths": [],
            "env_vars": [],
            "urls": [],
        }

        # File paths
        file_pattern = r'["\'](?:\.\.?/)?[^"\']+\.(?:yaml|yml|json|txt)["\']'
        for match in re.finditer(file_pattern, content):
            refs["file_paths"].append(match.group(0).strip("\"'"))

        # Environment variables (${VAR} syntax)
        env_pattern = r"\$\{([A-Z_][A-Z0-9_]*)\}"
        for match in re.finditer(env_pattern, content):
            refs["env_vars"].append(match.group(1))

        # URLs
        url_pattern = r'https?://[^\s"\']+'
        for match in re.finditer(url_pattern, content):
            refs["urls"].append(match.group(0))

        return refs

    def _extract_text_refs(self, content: str, filepath: str) -> dict[str, list[str]]:
        """Extract text file references."""
        refs = {
            "urls": [],
            "file_paths": [],
        }

        # URLs
        url_pattern = r"https?://[^\s]+"
        for match in re.finditer(url_pattern, content):
            refs["urls"].append(match.group(0))

        # File paths
        file_pattern = r"(?:\.\.?/)?[^\s]+\.(?:txt|md|json|yaml|yml)"
        for match in re.finditer(file_pattern, content):
            refs["file_paths"].append(match.group(0))

        return refs

    def _extract_config_refs(self, content: str, filepath: str) -> dict[str, list[str]]:
        """Extract config file references."""
        refs = {
            "includes": [],
            "file_paths": [],
        }

        # Include directives
        include_pattern = r'include\s+["\']?([^\s"\']+)["\']?'
        for match in re.finditer(include_pattern, content, re.IGNORECASE):
            refs["includes"].append(match.group(1))

        # File paths
        file_pattern = r'["\'](?:\.\.?/)?[^"\']+\.(?:conf|config|ini)["\']'
        for match in re.finditer(file_pattern, content):
            refs["file_paths"].append(match.group(0).strip("\"'"))

        return refs

    def _extract_makefile_refs(self, content: str, filepath: str) -> dict[str, list[str]]:
        """Extract Makefile references."""
        refs = {
            "includes": [],
            "file_paths": [],
            "commands": [],
        }

        # Include directives
        include_pattern = r"include\s+([^\s]+)"
        for match in re.finditer(include_pattern, content):
            refs["includes"].append(match.group(1))

        # File paths in targets
        file_pattern = r"[^:\s]+\.(?:py|sh|md|txt|json|yaml|yml):"
        for match in re.finditer(file_pattern, content):
            refs["file_paths"].append(match.group(0).rstrip(":"))

        return refs

    def extract_all_references(self) -> dict[str, dict]:
        """Extract references from all files."""
        exclude_patterns = [
            ".git",
            "__pycache__",
            ".venv",
            "venv",
            "node_modules",
            "PHASE",
            "QUBS_",
            "FINAL_REPORT",
            "MASTER_DEBUG_REPORT",
            "INSTALLER_TEST_REPORT",
        ]

        for root, dirs, files in os.walk(self.root_dir):
            # Filter out excluded directories
            dirs[:] = [d for d in dirs if not any(p in d for p in exclude_patterns)]

            for file in files:
                filepath = os.path.join(root, file)
                if any(p in filepath for p in exclude_patterns):
                    continue

                try:
                    with open(filepath, encoding="utf-8", errors="ignore") as f:
                        content = f.read()

                    ext = os.path.splitext(file)[1].lower()
                    if ext in self.file_types:
                        refs = self.file_types[ext](content, filepath)
                    elif file == "Makefile":
                        refs = self._extract_makefile_refs(content, filepath)
                    else:
                        refs = {"raw": [content[:500]]}  # Fallback

                    self.all_references[filepath] = refs

                except Exception as e:
                    self.all_references[filepath] = {"error": str(e)}

        return self.all_references

    def save_report(self, output_file: str):
        """Save extracted references to JSON file."""
        with open(output_file, "w") as f:
            json.dump(self.all_references, f, indent=2)


if __name__ == "__main__":
    extractor = ReferenceExtractor(".")
    references = extractor.extract_all_references()
    extractor.save_report("/tmp/phase2_references.json")

    print(f"Extracted references from {len(references)} files")
    print("Report saved to /tmp/phase2_references.json")

    # Print summary
    print("\n=== REFERENCE SUMMARY ===")
    for filepath, refs in list(references.items())[:10]:
        print(f"\n{filepath}:")
        for category, items in refs.items():
            if items:
                print(f"  {category}: {items[:3]}{'...' if len(items) > 3 else ''}")
