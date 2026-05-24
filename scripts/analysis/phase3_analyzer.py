#!/usr/bin/env python3
"""
Phase 3: Line-by-Line Code Analyzer
Performs static analysis on Python files to find potential issues.
"""

import os
import re
import ast
from typing import Dict, List, Set, Tuple
from pathlib import Path


class CodeAnalyzer:
    def __init__(self, root_dir: str = '.'):
        self.root_dir = root_dir
        self.issues: List[Dict] = []
        self.current_file: str = ""
        self.current_line: int = 0

    def analyze_file(self, filepath: str):
        """Analyze a single Python file."""
        self.current_file = filepath
        
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # Try to parse as AST
            try:
                tree = ast.parse(content, filename=filepath)
                self._analyze_ast(tree, content)
            except SyntaxError as e:
                self.issues.append({
                    'file': filepath,
                    'line': e.lineno,
                    'column': e.offset,
                    'type': 'SYNTAX_ERROR',
                    'message': f"Syntax error: {e.msg}",
                    'severity': 'CRITICAL'
                })
            
            # Also do regex-based analysis
            self._analyze_with_regex(content, filepath)
            
        except Exception as e:
            self.issues.append({
                'file': filepath,
                'line': 0,
                'column': 0,
                'type': 'ANALYSIS_ERROR',
                'message': f"Failed to analyze: {str(e)}",
                'severity': 'LOW'
            })

    def _analyze_ast(self, tree: ast.AST, content: str):
        """Analyze AST for potential issues."""
        lines = content.split('\n')
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self._check_import(alias.name, node.lineno, lines)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    self._check_from_import(node.module, alias.name, node.level, node.lineno, lines)
            elif isinstance(node, ast.Name):
                # Check for undefined variables
                if isinstance(node.ctx, ast.Load):
                    self._check_undefined_name(node.id, node.lineno, lines)
            elif isinstance(node, ast.Call):
                # Check for potential issues in function calls
                self._check_function_call(node, lines)
            elif isinstance(node, ast.FunctionDef):
                self._check_function_def(node, lines)
            elif isinstance(node, ast.ClassDef):
                self._check_class_def(node, lines)

    def _analyze_with_regex(self, content: str, filepath: str):
        """Analyze file using regex patterns."""
        lines = content.split('\n')
        
        # Check for hardcoded passwords/secrets
        secret_patterns = [
            r'password\s*=\s*["\'][^"\']+["\']',
            r'api_key\s*=\s*["\'][^"\']+["\']',
            r'secret\s*=\s*["\'][^"\']+["\']',
            r'token\s*=\s*["\'][^"\']+["\']',
        ]
        
        for i, line in enumerate(lines, 1):
            for pattern in secret_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    self.issues.append({
                        'file': filepath,
                        'line': i,
                        'column': 0,
                        'type': 'SECURITY',
                        'message': f"Potential hardcoded secret: {line.strip()[:50]}",
                        'severity': 'CRITICAL'
                    })
        
        # Check for SQL injection vulnerabilities
        sql_patterns = [
            r'execute\(.*\+.*\)',  # String concatenation in execute
            r'format\(.*\)\s*in\s*execute',
        ]
        
        for i, line in enumerate(lines, 1):
            for pattern in sql_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    self.issues.append({
                        'file': filepath,
                        'line': i,
                        'column': 0,
                        'type': 'SECURITY',
                        'message': f"Potential SQL injection: {line.strip()[:50]}",
                        'severity': 'HIGH'
                    })
        
        # Check for open() without with statement
        open_pattern = r'open\([^)]+\)\s*(?!with)'
        for i, line in enumerate(lines, 1):
            if re.search(open_pattern, line):
                # Check if it's in a with statement
                context = '\n'.join(lines[max(0, i-5):i+5])
                if 'with open(' not in context:
                    self.issues.append({
                        'file': filepath,
                        'line': i,
                        'column': 0,
                        'type': 'RESOURCE_LEAK',
                        'message': f"open() without with statement: {line.strip()[:50]}",
                        'severity': 'MEDIUM'
                    })
        
        # Check for print statements (should use logging)
        for i, line in enumerate(lines, 1):
            if re.search(r'\bprint\(', line):
                self.issues.append({
                    'file': filepath,
                    'line': i,
                    'column': 0,
                    'type': 'STYLE',
                    'message': f"print() statement found (use logging): {line.strip()[:50]}",
                    'severity': 'LOW'
                })
        
        # Check for TODO comments
        for i, line in enumerate(lines, 1):
            if re.search(r'#\s*TODO', line, re.IGNORECASE):
                self.issues.append({
                    'file': filepath,
                    'line': i,
                    'column': 0,
                    'type': 'TODO',
                    'message': f"TODO found: {line.strip()}",
                    'severity': 'INFO'
                })

    def _check_import(self, module: str, line: int, lines: List[str]):
        """Check import statement."""
        # Check for wildcard imports
        if module == '*':
            self.issues.append({
                'file': self.current_file,
                'line': line,
                'column': 0,
                'type': 'STYLE',
                'message': f"Wildcard import: from {module}",
                'severity': 'LOW'
            })

    def _check_from_import(self, module: str, name: str, level: int, line: int, lines: List[str]):
        """Check from import statement."""
        # Check for wildcard imports
        if name == '*':
            self.issues.append({
                'file': self.current_file,
                'line': line,
                'column': 0,
                'type': 'STYLE',
                'message': f"Wildcard import: from {module} import *",
                'severity': 'LOW'
            })

    def _check_undefined_name(self, name: str, line: int, lines: List[str]):
        """Check for undefined names."""
        # Skip common builtins
        builtins = {
            'print', 'len', 'str', 'int', 'float', 'bool', 'list', 'dict', 'set', 'tuple',
            'range', 'open', 'type', 'isinstance', 'hasattr', 'getattr', 'setattr',
            'min', 'max', 'sum', 'sorted', 'reversed', 'enumerate', 'zip', 'map', 'filter',
            'all', 'any', 'abs', 'round', 'pow', 'divmod',
            'object', 'property', 'staticmethod', 'classmethod',
            'True', 'False', 'None',
            'Exception', 'ValueError', 'TypeError', 'KeyError', 'IndexError', 'AttributeError',
            'ImportError', 'ModuleNotFoundError',
        }
        
        if name not in builtins and not name.startswith('_') and not name.isupper():
            # This might be an undefined variable, but we can't be sure without full analysis
            # For now, just flag it as a potential issue
            pass

    def _check_function_call(self, node: ast.Call, lines: List[str]):
        """Check function call for potential issues."""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            
            # Check for eval()
            if func_name == 'eval':
                self.issues.append({
                    'file': self.current_file,
                    'line': node.lineno,
                    'column': node.col_offset,
                    'type': 'SECURITY',
                    'message': f"Use of eval() is dangerous",
                    'severity': 'HIGH'
                })
            
            # Check for exec()
            if func_name == 'exec':
                self.issues.append({
                    'file': self.current_file,
                    'line': node.lineno,
                    'column': node.col_offset,
                    'type': 'SECURITY',
                    'message': f"Use of exec() is dangerous",
                    'severity': 'HIGH'
                })
            
            # Check for pickle.loads()
            if func_name == 'loads' and hasattr(node.func, 'value') and isinstance(node.func.value, ast.Name) and node.func.value.id == 'pickle':
                self.issues.append({
                    'file': self.current_file,
                    'line': node.lineno,
                    'column': node.col_offset,
                    'type': 'SECURITY',
                    'message': f"Use of pickle.loads() is dangerous",
                    'severity': 'HIGH'
                })

    def _check_function_def(self, node: ast.FunctionDef, lines: List[str]):
        """Check function definition for potential issues."""
        # Check for functions without docstrings
        if not ast.get_docstring(node):
            self.issues.append({
                'file': self.current_file,
                'line': node.lineno,
                'column': node.col_offset,
                'type': 'STYLE',
                'message': f"Function '{node.name}' has no docstring",
                'severity': 'LOW'
            })
        
        # Check for functions with too many parameters
        if len(node.args.args) > 10:
            self.issues.append({
                'file': self.current_file,
                'line': node.lineno,
                'column': node.col_offset,
                'type': 'STYLE',
                'message': f"Function '{node.name}' has {len(node.args.args)} parameters (consider refactoring)",
                'severity': 'LOW'
            })

    def _check_class_def(self, node: ast.ClassDef, lines: List[str]):
        """Check class definition for potential issues."""
        # Check for classes without docstrings
        if not ast.get_docstring(node):
            self.issues.append({
                'file': self.current_file,
                'line': node.lineno,
                'column': node.col_offset,
                'type': 'STYLE',
                'message': f"Class '{node.name}' has no docstring",
                'severity': 'LOW'
            })

    def analyze_directory(self, directory: str):
        """Analyze all Python files in a directory."""
        exclude_patterns = [
            '.git',
            '__pycache__',
            '.venv',
            'venv',
            'node_modules',
            'PHASE',
            'QUBS_',
            'FINAL_REPORT',
            'MASTER_DEBUG_REPORT',
            'INSTALLER_TEST_REPORT'
        ]
        
        for root, dirs, files in os.walk(directory):
            # Filter out excluded directories
            dirs[:] = [d for d in dirs if not any(p in d for p in exclude_patterns)]
            
            for file in files:
                if file.endswith('.py'):
                    filepath = os.path.join(root, file)
                    if not any(p in filepath for p in exclude_patterns):
                        self.analyze_file(filepath)

    def save_report(self, output_file: str):
        """Save analysis report to JSON file."""
        import json
        with open(output_file, 'w') as f:
            json.dump(self.issues, f, indent=2)

    def print_summary(self):
        """Print summary of analysis results."""
        print("\n" + "="*80)
        print("PHASE 3 CODE ANALYSIS SUMMARY")
        print("="*80)
        
        # Group by severity
        by_severity = {'CRITICAL': [], 'HIGH': [], 'MEDIUM': [], 'LOW': [], 'INFO': []}
        for issue in self.issues:
            severity = issue.get('severity', 'LOW')
            by_severity[severity].append(issue)
        
        print(f"\nTotal issues found: {len(self.issues)}")
        for severity in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO']:
            count = len(by_severity[severity])
            print(f"  {severity}: {count}")
        
        print("\n" + "="*80)
        print("CRITICAL ISSUES")
        print("="*80)
        for issue in by_severity['CRITICAL'][:20]:
            print(f"\n  {issue['file']}:{issue['line']}")
            print(f"    Type: {issue['type']}")
            print(f"    Message: {issue['message']}")
        
        if len(by_severity['CRITICAL']) > 20:
            print(f"\n  ... and {len(by_severity['CRITICAL']) - 20} more")
        
        print("\n" + "="*80)
        print("HIGH ISSUES")
        print("="*80)
        for issue in by_severity['HIGH'][:20]:
            print(f"\n  {issue['file']}:{issue['line']}")
            print(f"    Type: {issue['type']}")
            print(f"    Message: {issue['message']}")
        
        if len(by_severity['HIGH']) > 20:
            print(f"\n  ... and {len(by_severity['HIGH']) - 20} more")


if __name__ == '__main__':
    analyzer = CodeAnalyzer()
    
    # Analyze main source directories
    print("Analyzing src/ directory...")
    analyzer.analyze_directory('src')
    
    print("Analyzing pillar2/src/ directory...")
    analyzer.analyze_directory('pillar2/src')
    
    print("Analyzing pillar3/src/ directory...")
    analyzer.analyze_directory('pillar3/src')
    
    print("Analyzing pillar4/src/ directory...")
    analyzer.analyze_directory('pillar4/src')
    
    analyzer.save_report('/tmp/phase3_issues.json')
    analyzer.print_summary()
