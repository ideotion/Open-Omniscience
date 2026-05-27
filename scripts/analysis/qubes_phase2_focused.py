#!/usr/bin/env python3
"""
Open-Omniscience Qubes Branch - PHASE 2: FOCUSED DEPENDENCY VERIFICATION
========================================================================

This is a FOCUSED version of Phase 2 that only checks Python source files
in the src/ directory, following the 7-phase debugging protocol.

RULES:
- NEVER SKIP any Python file in src/
- ALWAYS VERIFY every reference exists and is correct
- DOCUMENT EVERYTHING
- PRIORITIZE RUTHLESSLY: Crashes > Data Corruption > Functional Bugs

This focused version:
1. Only processes Python files in src/ directory
2. Verifies all imports and internal references
3. Flags broken references as CRITICAL bugs
4. Generates a concise report of actual issues
"""

import os
import re
import json
import ast
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Set
import argparse


class FocusedDependencyChecker:
    """Focused dependency verifier for Python source files only."""
    
    def __init__(self, root_path: str):
        """
        Initialize the focused dependency checker.
        
        Args:
            root_path: Root directory of the codebase
        """
        self.root_path = os.path.abspath(root_path)
        self.src_path = os.path.join(self.root_path, 'src')
        self.all_python_files: List[str] = []
        self.issues: List[Dict[str, Any]] = []
        self.references: Dict[str, List[Dict[str, Any]]] = {}
        self.stats: Dict[str, Any] = {
            'total_files': 0,
            'total_references': 0,
            'verified_references': 0,
            'broken_references': 0,
            'by_type': {},
            'by_file': {}
        }
        
        # Find all Python files in src/
        self._find_python_files()
    
    def _find_python_files(self) -> None:
        """Find all Python files in src/ directory."""
        exclude_patterns = ['__pycache__', '.pytest_cache']
        
        if not os.path.exists(self.src_path):
            print(f"Warning: {self.src_path} not found")
            return
        
        for root, dirs, files in os.walk(self.src_path):
            # Filter out excluded directories
            dirs[:] = [d for d in dirs if not any(p in d for p in exclude_patterns)]
            
            for file in files:
                if file.endswith('.py'):
                    filepath = os.path.join(root, file)
                    rel_path = os.path.relpath(filepath, self.root_path)
                    self.all_python_files.append(rel_path)
        
        self.all_python_files.sort()
    
    def extract_imports_from_python(self, filepath: str) -> List[Dict[str, Any]]:
        """Extract all imports from a Python file."""
        references = []
        full_path = os.path.join(self.root_path, filepath)
        
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
                tree = ast.parse(content, filename=filepath)
            
            # Extract imports
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        ref = {
                            'type': 'import',
                            'file': filepath,
                            'line': node.lineno,
                            'module': alias.name,
                            'alias': alias.asname,
                            'category': 'module'
                        }
                        references.append(ref)
                        
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ''
                    for alias in node.names:
                        ref = {
                            'type': 'import_from',
                            'file': filepath,
                            'line': node.lineno,
                            'module': module,
                            'symbol': alias.name,
                            'alias': alias.asname,
                            'level': node.level,
                            'category': 'module'
                        }
                        references.append(ref)
            
        except SyntaxError as e:
            self.issues.append({
                'type': 'syntax_error',
                'file': filepath,
                'line': e.lineno,
                'message': str(e),
                'severity': 'CRITICAL'
            })
        except Exception as e:
            self.issues.append({
                'type': 'parse_error',
                'file': filepath,
                'message': str(e),
                'severity': 'HIGH'
            })
        
        return references
    
    def verify_import(self, ref: Dict[str, Any]) -> Dict[str, Any]:
        """Verify a single import reference."""
        result = {
            'reference': ref,
            'verified': False,
            'message': '',
            'severity': 'LOW'
        }
        
        ref_type = ref.get('type', '')
        
        if ref_type == 'import':
            module = ref.get('module', '')
            result = self._verify_module_import(module, ref, result)
        elif ref_type == 'import_from':
            module = ref.get('module', '')
            symbol = ref.get('symbol', '')
            level = ref.get('level', 0)
            result = self._verify_from_import(module, symbol, level, ref, result)
        
        return result
    
    def _verify_module_import(self, module: str, ref: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        """Verify a module import (e.g., import numpy)."""
        if not module:
            result['message'] = 'Empty module name'
            result['severity'] = 'LOW'
            return result
        
        # Check if it's a relative import (shouldn't happen for 'import' type, but just in case)
        if module.startswith('.'):
            result = self._verify_relative_import(module, ref, result)
            return result
        
        # Check if it's a standard library module
        stdlib_modules = {
            'os', 'sys', 'json', 're', 'ast', 'pathlib', 'datetime', 'time', 'argparse',
            'collections', 'itertools', 'functools', 'operator', 'copy', 'pickle',
            'hashlib', 'hmac', 'base64', 'binascii', 'struct', 'array',
            'math', 'random', 'statistics', 'decimal', 'fractions',
            'urllib', 'http', 'ftplib', 'smtplib', 'poplib', 'imaplib',
            'socket', 'ssl', 'asyncio', 'asyncore', 'concurrent',
            'threading', 'multiprocessing', 'subprocess', 'signal',
            'logging', 'traceback', 'linecache', 'tokenize', 'token',
            'abc', 'typing', 'dataclasses', 'enum', 'functools',
            'unittest', 'doctest', 'pdb', 'profile', 'pstats',
            'gc', 'inspect', 'dis', 'resource', 'sysconfig',
            'platform', 'webbrowser', 'tempfile', 'glob', 'fnmatch',
            'fileinput', 'filecmp', 'difflib', 'textwrap', 'unicodedata',
            'string', 're', 'sre_compile', 'sre_parse', 'sre_constants',
            # Additional stdlib modules
            'urllib.parse', 'urllib.request', 'urllib.error', 'urllib.robotparser',
            'http.client', 'http.server', 'http.cookies', 'http.cookiejar',
            'email', 'email.message', 'email.mime', 'email.parser',
            'socketserver', 'xml', 'xml.etree', 'xml.etree.ElementTree',
            'xml.dom', 'xml.sax', 'xml.parsers',
            'csv', 'configparser', 'getopt', 'optparse',
            'zipfile', 'tarfile', 'gzip', 'bz2', 'lzma', 'zlib',
            'code', 'codeop', 'compileall', 'py_compile',
            'importlib', 'importlib.util', 'importlib.abc', 'importlib.machinery',
            'runpy', 'builtins', '__main__', '__future__',
            'atexit', 'warnings', 'contextlib', 'contextvars',
            'copyreg', 'types', 'fpectl', 'pprint', 'reprlib',
            'textwrap', 'stringprep', 'difflib',
            'logging.handlers', 'logging.config',
            'ctypes', 'ctypes.util',
            'mmap', 'codecs', 'encodings',
            'io', 'abc', 'warnings',
            # Additional stdlib modules
            'sqlite3', 'shutil', 'sqlite3.dbapi2',
            # Qubes-specific additions
            'qubes', 'qubes.rpc', 'qubes.vm',
        }
        
        if module in stdlib_modules or module.split('.')[0] in stdlib_modules:
            result['verified'] = True
            result['message'] = f'Standard library module: {module}'
            return result
        
        # Check if it's in the codebase
        # Convert dotted module name to file path
        module_file_path = module.replace('.', '/')
        
        # If module starts with 'src.', strip it for path resolution
        if module.startswith('src.'):
            module_file_path = module[4:].replace('.', '/')
        
        possible_paths = [
            os.path.join(self.root_path, module_file_path + '.py'),
            os.path.join(self.root_path, module_file_path, '__init__.py'),
            os.path.join(self.src_path, module_file_path + '.py'),
            os.path.join(self.src_path, module_file_path, '__init__.py'),
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                result['verified'] = True
                result['message'] = f'Module {module} exists in codebase'
                return result
        
        # Module not found - this is a real issue
        result['message'] = f'Module {module} not found (not stdlib, not in codebase)'
        result['severity'] = 'CRITICAL'
        
        return result
    
    def _verify_from_import(self, module: str, symbol: str, level: int, ref: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        """Verify a from import (e.g., from src.database.models import Article)."""
        if not module:
            result['message'] = 'Empty module name'
            result['severity'] = 'LOW'
            return result
        
        # Handle relative imports
        if module.startswith('.') or level > 0:
            result = self._verify_relative_import(module, ref, result, symbol)
            return result
        
        # Check if it's a standard library module
        stdlib_modules = {
            'os', 'sys', 'json', 're', 'ast', 'pathlib', 'datetime', 'time', 'argparse',
            'collections', 'itertools', 'functools', 'operator', 'copy', 'pickle',
            'hashlib', 'hmac', 'base64', 'binascii', 'struct', 'array',
            'math', 'random', 'statistics', 'decimal', 'fractions',
            'urllib', 'http', 'ftplib', 'smtplib', 'poplib', 'imaplib',
            'socket', 'ssl', 'asyncio', 'asyncore', 'concurrent',
            'threading', 'multiprocessing', 'subprocess', 'signal',
            'logging', 'traceback', 'linecache', 'tokenize', 'token',
            'abc', 'typing', 'dataclasses', 'enum', 'functools',
            'unittest', 'doctest', 'pdb', 'profile', 'pstats',
            'gc', 'inspect', 'dis', 'resource', 'sysconfig',
            'platform', 'webbrowser', 'tempfile', 'glob', 'fnmatch',
            'fileinput', 'filecmp', 'difflib', 'textwrap', 'unicodedata',
            'string', 're', 'sre_compile', 'sre_parse', 'sre_constants',
            'urllib.parse', 'urllib.request', 'urllib.error', 'urllib.robotparser',
            'http.client', 'http.server', 'http.cookies', 'http.cookiejar',
            'email', 'email.message', 'email.mime', 'email.parser',
            'socketserver', 'xml', 'xml.etree', 'xml.etree.ElementTree',
            'xml.dom', 'xml.sax', 'xml.parsers',
            'csv', 'configparser', 'getopt', 'optparse',
            'zipfile', 'tarfile', 'gzip', 'bz2', 'lzma', 'zlib',
            'code', 'codeop', 'compileall', 'py_compile',
            'importlib', 'importlib.util', 'importlib.abc', 'importlib.machinery',
            'runpy', 'builtins', '__main__', '__future__',
            'atexit', 'warnings', 'contextlib', 'contextvars',
            'copyreg', 'types', 'fpectl', 'pprint', 'reprlib',
            'textwrap', 'stringprep', 'difflib',
            'logging.handlers', 'logging.config',
            'ctypes', 'ctypes.util',
            'mmap', 'codecs', 'encodings',
            'io', 'warnings',
            # Additional stdlib modules
            'sqlite3', 'shutil', 'sqlite3.dbapi2',
        }
        
        if module in stdlib_modules or module.split('.')[0] in stdlib_modules:
            # For stdlib modules, we can't verify the symbol exists without importing
            # So we'll just verify the module is stdlib
            result['verified'] = True
            result['message'] = f'Standard library module: {module}'
            return result
        
        # Check if module exists
        # Convert dotted module name to file path
        module_file_path = module.replace('.', '/')
        
        # If module starts with 'src.', strip it for path resolution
        if module.startswith('src.'):
            module_file_path = module[4:].replace('.', '/')
        
        module_path = None
        possible_paths = [
            os.path.join(self.root_path, module_file_path + '.py'),
            os.path.join(self.root_path, module_file_path, '__init__.py'),
            os.path.join(self.src_path, module_file_path + '.py'),
            os.path.join(self.src_path, module_file_path, '__init__.py'),
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                module_path = path
                break
        
        if not module_path:
            # Module doesn't exist
            result['message'] = f'Module {module} not found'
            result['severity'] = 'CRITICAL'
            return result
        
        # Module exists, check if symbol exists in it
        if self._check_symbol_in_module(module_path, symbol):
            result['verified'] = True
            result['message'] = f'Symbol {symbol} found in module {module}'
        else:
            result['message'] = f'Symbol {symbol} not found in module {module}'
            result['severity'] = 'CRITICAL'
        
        return result
    
    def _verify_relative_import(self, module: str, ref: Dict[str, Any], result: Dict[str, Any], symbol: str = None) -> Dict[str, Any]:
        """Verify a relative import."""
        file = ref.get('file', '')
        file_dir = os.path.dirname(os.path.join(self.root_path, file))
        level = ref.get('level', 0)
        
        # For relative imports in Python:
        # level = 0 means absolute import (not relative)
        # level = 1 means from current package (.)
        # level = 2 means from parent package (..)
        # level = 3 means from grandparent package (...)
        # etc.
        
        # Go up (level - 1) directories because:
        # - level 1 (.) means current directory, so go up 0 levels
        # - level 2 (..) means parent directory, so go up 1 level
        # - level 3 (...) means grandparent directory, so go up 2 levels
        current_dir = file_dir
        for _ in range(level - 1):
            current_dir = os.path.dirname(os.path.normpath(current_dir))
        
        # Now resolve the module path
        if module:
            # Split by dots and resolve each part
            parts = module.split('.')
            for part in parts:
                if not part:
                    continue
                check_path = os.path.join(current_dir, part)
                # Check for .py file first
                if os.path.exists(check_path + '.py'):
                    current_dir = check_path + '.py'
                # Then check for directory (package)
                elif os.path.exists(check_path):
                    current_dir = check_path
                else:
                    result['message'] = f'Relative import not found: {module} from {file} (level={level})'
                    result['severity'] = 'CRITICAL'
                    return result
        
        # If we have a symbol to check (for import_from)
        if symbol:
            if os.path.isfile(current_dir):
                if self._check_symbol_in_module(current_dir, symbol):
                    result['verified'] = True
                    result['message'] = f'Symbol {symbol} found in relative module {module}'
                else:
                    result['message'] = f'Symbol {symbol} not found in relative module {module}'
                    result['severity'] = 'CRITICAL'
            else:
                # It's a directory, check for __init__.py
                init_path = os.path.join(current_dir, '__init__.py')
                if os.path.exists(init_path):
                    if self._check_symbol_in_module(init_path, symbol):
                        result['verified'] = True
                        result['message'] = f'Symbol {symbol} found in {init_path}'
                    else:
                        result['message'] = f'Symbol {symbol} not found in {init_path}'
                        result['severity'] = 'CRITICAL'
                else:
                    result['message'] = f'No __init__.py in {current_dir}'
                    result['severity'] = 'CRITICAL'
        else:
            # For regular import, just check if the module exists
            if os.path.exists(current_dir):
                result['verified'] = True
                result['message'] = f'Relative import resolved: {module}'
            else:
                result['message'] = f'Relative import not found: {module}'
                result['severity'] = 'CRITICAL'
        
        return result
        
        # If we have a symbol to check (for import_from)
        if symbol:
            if os.path.isfile(current_dir):
                if self._check_symbol_in_module(current_dir, symbol):
                    result['verified'] = True
                    result['message'] = f'Symbol {symbol} found in relative module {module}'
                else:
                    result['message'] = f'Symbol {symbol} not found in relative module {module}'
                    result['severity'] = 'CRITICAL'
            else:
                # It's a directory, check for __init__.py
                init_path = os.path.join(current_dir, '__init__.py')
                if os.path.exists(init_path):
                    if self._check_symbol_in_module(init_path, symbol):
                        result['verified'] = True
                        result['message'] = f'Symbol {symbol} found in {init_path}'
                    else:
                        result['message'] = f'Symbol {symbol} not found in {init_path}'
                        result['severity'] = 'CRITICAL'
                else:
                    result['message'] = f'No __init__.py in {current_dir}'
                    result['severity'] = 'CRITICAL'
        else:
            # For regular import, just check if the module exists
            if os.path.exists(current_dir):
                result['verified'] = True
                result['message'] = f'Relative import resolved: {module}'
            else:
                result['message'] = f'Relative import not found: {module}'
                result['severity'] = 'CRITICAL'
        
        return result
    
    def _check_symbol_in_module(self, module_path: str, symbol: str) -> bool:
        """Check if a symbol exists in a module file (definition or import)."""
        try:
            with open(module_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Parse the file and look for the symbol
            tree = ast.parse(content, filename=module_path)
            
            # Look for class, function, or variable definitions
            for node in ast.walk(tree):
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name == symbol:
                        return True
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == symbol:
                            return True
                elif isinstance(node, ast.AnnAssign):
                    if isinstance(node.target, ast.Name) and node.target.id == symbol:
                        return True
                # Check for imports
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == symbol or alias.asname == symbol:
                            return True
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        if alias.name == symbol or alias.asname == symbol:
                            return True
            
            return False
        except Exception:
            return False
    
    def run(self) -> Dict[str, Any]:
        """Run the focused dependency verification."""
        print(f"\n{'='*80}")
        print(f"PHASE 2: FOCUSED DEPENDENCY VERIFICATION (Python files in src/)")
        print(f"{'='*80}")
        print(f"Root Path: {self.root_path}")
        print(f"Python Files to Analyze: {len(self.all_python_files)}")
        print(f"Start Time: {datetime.now().isoformat()}")
        print(f"{'='*80}\n")
        
        start_time = datetime.now()
        
        # Process each Python file
        for i, filepath in enumerate(self.all_python_files, 1):
            print(f"[{i}/{len(self.all_python_files)}] Analyzing {filepath}...")
            
            # Extract imports
            references = self.extract_imports_from_python(filepath)
            self.references[filepath] = references
            self.stats['total_references'] += len(references)
            self.stats['by_file'][filepath] = len(references)
            
            # Categorize references
            for ref in references:
                ref_type = ref.get('type', 'unknown')
                if ref_type not in self.stats['by_type']:
                    self.stats['by_type'][ref_type] = 0
                self.stats['by_type'][ref_type] += 1
            
            # Verify each import
            for ref in references:
                verification = self.verify_import(ref)
                
                if verification['verified']:
                    self.stats['verified_references'] += 1
                else:
                    self.stats['broken_references'] += 1
                    
                    # Create issue for broken import
                    issue = {
                        'type': 'broken_import',
                        'file': filepath,
                        'line': ref.get('line', 'N/A'),
                        'ref_type': ref.get('type', 'unknown'),
                        'module': ref.get('module', 'N/A'),
                        'symbol': ref.get('symbol', 'N/A'),
                        'message': verification['message'],
                        'severity': verification['severity'],
                        'timestamp': datetime.now().isoformat()
                    }
                    self.issues.append(issue)
        
        # Calculate duration
        duration = (datetime.now() - start_time).total_seconds()
        
        # Print summary
        print(f"\n{'='*80}")
        print(f"PHASE 2 FOCUSED SUMMARY")
        print(f"{'='*80}")
        print(f"Total Python Files Analyzed: {len(self.all_python_files)}")
        print(f"Total Imports Extracted: {self.stats['total_references']}")
        print(f"Verified Imports: {self.stats['verified_references']}")
        print(f"Broken Imports: {self.stats['broken_references']}")
        print(f"Duration: {duration:.2f} seconds")
        print(f"{'='*80}\n")
        
        # Print issues by severity
        if self.issues:
            print(f"{'='*80}")
            print(f"CRITICAL ISSUES FOUND: {len([i for i in self.issues if i.get('severity') == 'CRITICAL'])}")
            print(f"{'='*80}\n")
            
            # Group by module
            by_module = {}
            for issue in self.issues:
                if issue.get('severity') == 'CRITICAL':
                    module = issue.get('module', issue.get('symbol', 'unknown'))
                    if module not in by_module:
                        by_module[module] = []
                    by_module[module].append(issue)
            
            for module, issues in sorted(by_module.items(), key=lambda x: len(x[1]), reverse=True):
                print(f"\n{module}: {len(issues)} references")
                for issue in issues[:3]:  # Show first 3
                    print(f"  {issue['file']}:{issue.get('line', '?')} - {issue['message']}")
                if len(issues) > 3:
                    print(f"  ... and {len(issues) - 3} more")
        else:
            print("No CRITICAL issues found! All imports verified.")
        
        return {
            'metadata': {
                'start_time': start_time.isoformat(),
                'end_time': datetime.now().isoformat(),
                'duration_seconds': duration,
                'branch': '0.02_Qubes',
                'focus': 'Python files in src/'
            },
            'stats': self.stats,
            'references': self.references,
            'issues': self.issues
        }
    
    def save_report(self, output_path: str) -> None:
        """Save the focused dependency verification report."""
        result = {
            'metadata': {
                'protocol': '7-Phase Debugging Protocol - Phase 2 (Focused)',
                'branch': '0.02_Qubes',
                'timestamp': datetime.now().isoformat(),
                'focus': 'Python files in src/'
            },
            'stats': self.stats,
            'issues': self.issues
        }
        
        with open(output_path, 'w') as f:
            json.dump(result, f, indent=2, default=str)
        
        print(f"\nReport saved to: {output_path}")
        print(f"Report size: {os.path.getsize(output_path) / 1024:.2f} KB")


def main():
    parser = argparse.ArgumentParser(
        description='Phase 2 Focused: Dependency Verification for Python files in src/'
    )
    parser.add_argument(
        '--root',
        type=str,
        default='.',
        help='Root directory to analyze (default: current directory)'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='QUBS_PHASE2_FOCUSED_REPORT.json',
        help='Output JSON file path (default: QUBS_PHASE2_FOCUSED_REPORT.json)'
    )
    
    args = parser.parse_args()
    
    # Initialize checker
    checker = FocusedDependencyChecker(args.root)
    
    if not checker.all_python_files:
        print(f"No Python files found in {checker.src_path}")
        sys.exit(1)
    
    # Run verification
    result = checker.run()
    
    # Save report
    checker.save_report(args.output)
    
    print(f"\n{'='*80}")
    print(f"PHASE 2 FOCUSED COMPLETE")
    print(f"{'='*80}")
    print(f"Next Step: Proceed to PHASE 3 - Line-by-Line Code Analysis")
    print(f"{'='*80}\n")


if __name__ == '__main__':
    main()
