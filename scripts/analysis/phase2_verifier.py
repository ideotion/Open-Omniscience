#!/usr/bin/env python3
"""
Phase 2: Reference Verifier
Verifies all extracted references against the filesystem and other sources.
"""

import os
import json
import requests
from pathlib import Path
from typing import Dict, List, Set, Tuple
from urllib.parse import urlparse


class ReferenceVerifier:
    def __init__(self, root_dir: str = '.', references_file: str = '/tmp/phase2_references.json'):
        self.root_dir = root_dir
        self.references_file = references_file
        self.issues: List[Dict] = []
        self.all_files: Set[str] = set()
        
        # Collect all files in the repository
        self._collect_all_files()

    def _collect_all_files(self):
        """Collect all file paths in the repository."""
        exclude_patterns = [
            '.git',
            '__pycache__',
            '.venv',
            'venv',
            'node_modules',
        ]
        
        for root, dirs, files in os.walk(self.root_dir):
            # Filter out excluded directories
            dirs[:] = [d for d in dirs if not any(p in d for p in exclude_patterns)]
            
            for file in files:
                filepath = os.path.normpath(os.path.join(root, file))
                self.all_files.add(filepath)

    def _normalize_path(self, path: str, source_file: str = None) -> str:
        """Normalize a path relative to source file or repo root."""
        if path.startswith('/'):
            return path
        
        if source_file:
            source_dir = os.path.dirname(source_file)
            return os.path.normpath(os.path.join(source_dir, path))
        
        return os.path.normpath(os.path.join(self.root_dir, path))

    def _file_exists(self, path: str) -> bool:
        """Check if a file exists (case-insensitive on some systems)."""
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

    def _check_url(self, url: str, timeout: int = 5) -> Tuple[bool, str]:
        """Check if a URL is reachable."""
        try:
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return False, "Invalid URL format"
            
            # Skip localhost and internal URLs
            if parsed.netloc in ['localhost', '127.0.0.1', '0.0.0.0']:
                return True, "Local URL (skipped)"
            
            # Only check HTTP/HTTPS
            if parsed.scheme not in ['http', 'https']:
                return True, "Non-HTTP URL (skipped)"
            
            # Try HEAD request first
            try:
                response = requests.head(url, timeout=timeout, allow_redirects=True)
                if response.status_code < 400:
                    return True, f"Reachable ({response.status_code})"
            except requests.HeadRequest:
                pass
            
            # Try GET if HEAD fails
            response = requests.get(url, timeout=timeout, stream=True)
            response.close()
            if response.status_code < 400:
                return True, f"Reachable ({response.status_code})"
            else:
                return False, f"HTTP {response.status_code}"
                
        except requests.RequestException as e:
            return False, f"Connection error: {str(e)}"
        except Exception as e:
            return False, f"Error: {str(e)}"

    def _check_python_module(self, module: str) -> Tuple[bool, str]:
        """Check if a Python module is importable."""
        try:
            __import__(module)
            return True, "Module found"
        except ImportError:
            return False, "Module not found"
        except Exception as e:
            return False, f"Error: {str(e)}"

    def _check_env_var(self, var: str, source_file: str = None) -> Tuple[bool, str]:
        """Check if an environment variable is defined in .env files."""
        # Check common .env files
        env_files = [
            os.path.join(self.root_dir, '.env'),
            os.path.join(self.root_dir, '.env.example'),
            os.path.join(self.root_dir, '.env.production'),
            os.path.join(self.root_dir, '.env.production.example'),
        ]
        
        for env_file in env_files:
            if os.path.exists(env_file):
                try:
                    with open(env_file, 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith('#') and '=' in line:
                                var_name = line.split('=', 1)[0].strip()
                                if var_name == var:
                                    return True, f"Found in {env_file}"
                except Exception:
                    pass
        
        return False, "Not found in .env files"

    def verify_references(self):
        """Verify all references from the extracted JSON."""
        try:
            with open(self.references_file, 'r') as f:
                references = json.load(f)
        except Exception as e:
            print(f"Error loading references: {e}")
            return
        
        print(f"Verifying references from {len(references)} files...")
        
        for filepath, refs in references.items():
            if 'error' in refs:
                continue
            
            # Get absolute path to source file
            abs_source_path = os.path.abspath(filepath)
            
            for category, items in refs.items():
                if not items or isinstance(items, list) and not items:
                    continue
                
                if category == 'imports':
                    for module in items:
                        if not module or module.isspace():
                            continue
                        # Clean up module name (remove newlines, etc.)
                        module = module.strip()
                        if not module:
                            continue
                        
                        # Skip if it's a multi-line import artifact
                        if '\n' in module or 'import' in module:
                            continue
                        
                        # Check if it's a standard library module
                        is_stdlib, msg = self._check_python_module(module)
                        if not is_stdlib:
                            self.issues.append({
                                'file': filepath,
                                'category': 'python_import',
                                'reference': module,
                                'status': 'MISSING',
                                'message': f"Python module '{module}' not found",
                                'severity': 'HIGH'
                            })
                
                elif category == 'from_imports':
                    for import_stmt in items:
                        if '->' in import_stmt:
                            module = import_stmt.split('->')[0].strip()
                            if module:
                                is_stdlib, msg = self._check_python_module(module)
                                if not is_stdlib:
                                    self.issues.append({
                                        'file': filepath,
                                        'category': 'python_from_import',
                                        'reference': module,
                                        'status': 'MISSING',
                                        'message': f"Python module '{module}' not found",
                                        'severity': 'HIGH'
                                    })
                
                elif category == 'file_paths':
                    for file_ref in items:
                        if not file_ref:
                            continue
                        
                        # Normalize the path
                        normalized = self._normalize_path(file_ref, abs_source_path)
                        
                        # Check if file exists
                        if not self._file_exists(normalized):
                            # Try relative to repo root
                            normalized_root = self._normalize_path(file_ref, self.root_dir)
                            if not self._file_exists(normalized_root):
                                self.issues.append({
                                    'file': filepath,
                                    'category': 'file_path',
                                    'reference': file_ref,
                                    'normalized': normalized,
                                    'status': 'MISSING',
                                    'message': f"File '{file_ref}' not found",
                                    'severity': 'CRITICAL'
                                })
                
                elif category == 'env_vars':
                    for var in items:
                        if not var:
                            continue
                        
                        found, msg = self._check_env_var(var, abs_source_path)
                        if not found:
                            self.issues.append({
                                'file': filepath,
                                'category': 'env_var',
                                'reference': var,
                                'status': 'MISSING',
                                'message': f"Environment variable '{var}' not defined",
                                'severity': 'MEDIUM'
                            })
                
                elif category == 'urls':
                    for url in items:
                        if not url:
                            continue
                        
                        reachable, msg = self._check_url(url)
                        if not reachable:
                            self.issues.append({
                                'file': filepath,
                                'category': 'url',
                                'reference': url,
                                'status': 'UNREACHABLE',
                                'message': msg,
                                'severity': 'LOW'
                            })
                
                elif category == 'requires':
                    for module in items:
                        if not module:
                            continue
                        
                        # For JS modules, we can't easily verify without npm
                        # Just log as info for now
                        pass
                
                elif category == 'links' or category == 'images':
                    for link in items:
                        if not link:
                            continue
                        
                        if link.startswith('http'):
                            reachable, msg = self._check_url(link)
                            if not reachable:
                                self.issues.append({
                                    'file': filepath,
                                    'category': 'url',
                                    'reference': link,
                                    'status': 'UNREACHABLE',
                                    'message': msg,
                                    'severity': 'LOW'
                                })
                        else:
                            # Local file reference
                            normalized = self._normalize_path(link, abs_source_path)
                            if not self._file_exists(normalized):
                                self.issues.append({
                                    'file': filepath,
                                    'category': 'file_path',
                                    'reference': link,
                                    'normalized': normalized,
                                    'status': 'MISSING',
                                    'message': f"Local reference '{link}' not found",
                                    'severity': 'MEDIUM'
                                })
                
                elif category == 'file_refs':
                    for ref in items:
                        if not ref:
                            continue
                        
                        if ref.startswith('http'):
                            reachable, msg = self._check_url(ref)
                            if not reachable:
                                self.issues.append({
                                    'file': filepath,
                                    'category': 'url',
                                    'reference': ref,
                                    'status': 'UNREACHABLE',
                                    'message': msg,
                                    'severity': 'LOW'
                                })
                        else:
                            normalized = self._normalize_path(ref, abs_source_path)
                            if not self._file_exists(normalized):
                                self.issues.append({
                                    'file': filepath,
                                    'category': 'file_path',
                                    'reference': ref,
                                    'normalized': normalized,
                                    'status': 'MISSING',
                                    'message': f"File reference '{ref}' not found",
                                    'severity': 'MEDIUM'
                                })

    def save_issues(self, output_file: str):
        """Save verification issues to JSON file."""
        with open(output_file, 'w') as f:
            json.dump(self.issues, f, indent=2)

    def print_summary(self):
        """Print summary of verification results."""
        print("\n" + "="*80)
        print("PHASE 2 VERIFICATION SUMMARY")
        print("="*80)
        
        # Group by severity
        by_severity = {'CRITICAL': [], 'HIGH': [], 'MEDIUM': [], 'LOW': []}
        for issue in self.issues:
            severity = issue.get('severity', 'LOW')
            by_severity[severity].append(issue)
        
        print(f"\nTotal issues found: {len(self.issues)}")
        for severity in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']:
            count = len(by_severity[severity])
            print(f"  {severity}: {count}")
        
        print("\n" + "="*80)
        print("CRITICAL ISSUES (File Path References)")
        print("="*80)
        for issue in by_severity['CRITICAL'][:20]:
            print(f"\n  File: {issue['file']}")
            print(f"    Reference: {issue['reference']}")
            print(f"    Message: {issue['message']}")
        
        if len(by_severity['CRITICAL']) > 20:
            print(f"\n  ... and {len(by_severity['CRITICAL']) - 20} more")


if __name__ == '__main__':
    verifier = ReferenceVerifier()
    verifier.verify_references()
    verifier.save_issues('/tmp/phase2_issues.json')
    verifier.print_summary()
