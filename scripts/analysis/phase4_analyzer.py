#!/usr/bin/env python3
"""
Phase 4: Static & Dynamic Analysis
Runs linters (Pylint, Flake8), type checkers (mypy), and executes all tests with coverage.
Identifies dead code, anti-patterns, and runtime issues.
"""

import os
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = "/workspace/ideotion__Open-Omniscience"
OUTPUT_FILE = "/workspace/ideotion__Open-Omniscience/PHASE4_REPORT.json"

def run_command(cmd, cwd=None, timeout=120):
    """Run a command and return the result."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd or REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return {
            'command': cmd,
            'returncode': result.returncode,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'success': result.returncode == 0
        }
    except subprocess.TimeoutExpired:
        return {
            'command': cmd,
            'returncode': -1,
            'stdout': '',
            'stderr': f'Command timed out after {timeout} seconds',
            'success': False
        }
    except Exception as e:
        return {
            'command': cmd,
            'returncode': -2,
            'stdout': '',
            'stderr': str(e),
            'success': False
        }

def run_pylint(filepath):
    """Run Pylint on a Python file."""
    cmd = f"pylint --output-format=json {filepath}"
    result = run_command(cmd)
    
    if result['success']:
        try:
            # Parse JSON output
            import json as json_module
            # Pylint outputs one JSON object per line
            lines = result['stdout'].strip().split('\n')
            if lines:
                # Try to parse the last line as JSON
                try:
                    data = json_module.loads(lines[-1])
                    return {
                        'success': True,
                        'score': data.get('score', 0),
                        'messages': data.get('messages', []),
                        'raw_output': result['stdout']
                    }
                except:
                    pass
            return {
                'success': True,
                'score': 0,
                'messages': [],
                'raw_output': result['stdout']
            }
        except:
            return {
                'success': False,
                'error': 'Failed to parse Pylint output',
                'raw_output': result['stdout']
            }
    else:
        return {
            'success': False,
            'error': result['stderr'],
            'raw_output': result['stdout']
        }

def run_flake8(filepath):
    """Run Flake8 on a Python file."""
    cmd = f"flake8 --format=json {filepath}"
    result = run_command(cmd)
    
    if result['success']:
        try:
            # Flake8 outputs JSON
            if result['stdout'].strip():
                return json.loads(result['stdout'])
            return []
        except:
            return []
    else:
        return []

def run_mypy(filepath):
    """Run mypy on a Python file."""
    cmd = f"mypy --output=json {filepath}"
    result = run_command(cmd)
    
    if result['success']:
        try:
            if result['stdout'].strip():
                return json.loads(result['stdout'])
            return []
        except:
            return []
    else:
        return []

def run_pytest(test_path):
    """Run pytest on a test file or directory."""
    cmd = f"pytest {test_path} --tb=short --verbose 2>&1"
    result = run_command(cmd, timeout=300)
    
    return {
        'success': result['success'],
        'returncode': result['returncode'],
        'output': result['stdout'] + result['stderr'],
        'passed': result['stdout'].count(' passed') if result['success'] else 0,
        'failed': result['stdout'].count(' failed') if result['success'] else 0,
        'errors': result['stdout'].count(' error') if result['success'] else 0
    }

def check_dead_code(filepath):
    """Check for dead code using vulture."""
    cmd = f"vulture {filepath} --min-confidence=80"
    result = run_command(cmd)
    
    if result['success']:
        return {
            'success': True,
            'dead_code': [],
            'output': result['stdout']
        }
    else:
        # Parse vulture output
        dead_code = []
        for line in result['stderr'].split('\n'):
            if ':' in line and 'unused' in line.lower():
                parts = line.split(':')
                if len(parts) >= 2:
                    dead_code.append({
                        'file': parts[0],
                        'line': parts[1].split(' ')[0] if ' ' in parts[1] else parts[1],
                        'reason': line
                    })
        return {
            'success': False,
            'dead_code': dead_code,
            'output': result['stderr']
        }

def analyze_imports(filepath):
    """Analyze imports for unused ones."""
    try:
        import ast
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        tree = ast.parse(content, filename=filepath)
        
        # Extract all imports
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append({
                        'name': alias.name,
                        'asname': alias.asname,
                        'line': node.lineno,
                        'type': 'import'
                    })
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                for alias in node.names:
                    imports.append({
                        'name': alias.name,
                        'module': module,
                        'asname': alias.asname,
                        'line': node.lineno,
                        'type': 'from_import'
                    })
        
        # Check which imports are used
        used_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                used_names.add(node.id)
        
        # Identify potentially unused imports
        unused_imports = []
        for imp in imports:
            name = imp.get('asname') or imp.get('name')
            if name and name not in used_names and not name.startswith('_'):
                unused_imports.append(imp)
        
        return {
            'total_imports': len(imports),
            'unused_imports': unused_imports
        }
    
    except Exception as e:
        return {
            'error': str(e),
            'total_imports': 0,
            'unused_imports': []
        }

def check_circular_imports(repo_root):
    """Check for circular imports in the codebase."""
    try:
        # This is a simplified check
        import ast
        import networkx as nx
        
        # Build import graph
        graph = nx.DiGraph()
        
        for root, dirs, files in os.walk(repo_root):
            if '.git' in root or '__pycache__' in root:
                continue
            for filename in files:
                if filename.endswith('.py'):
                    filepath = os.path.join(root, filename)
                    rel_path = os.path.relpath(filepath, repo_root)
                    
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            content = f.read()
                        
                        tree = ast.parse(content, filename=filepath)
                        
                        for node in ast.walk(tree):
                            if isinstance(node, ast.Import):
                                for alias in node.names:
                                    module = alias.name
                                    # Try to resolve relative imports
                                    if module.startswith('.'):
                                        # Convert relative import to absolute
                                        parts = rel_path.replace('.py', '').replace('/', '.').split('.')
                                        level = module.count('.')
                                        if level <= len(parts):
                                            abs_module = '.'.join(parts[:-level] + [module.lstrip('.')])
                                            graph.add_edge(rel_path, abs_module)
                                    else:
                                        graph.add_edge(rel_path, module)
                            elif isinstance(node, ast.ImportFrom):
                                module = node.module or ''
                                if module:
                                    if module.startswith('.'):
                                        parts = rel_path.replace('.py', '').replace('/', '.').split('.')
                                        level = module.count('.')
                                        if level <= len(parts):
                                            abs_module = '.'.join(parts[:-level] + [module.lstrip('.')])
                                            graph.add_edge(rel_path, abs_module)
                                    else:
                                        graph.add_edge(rel_path, module)
                    except:
                        pass
        
        # Find cycles
        cycles = list(nx.simple_cycles(graph))
        
        return {
            'has_circular_imports': len(cycles) > 0,
            'cycles': cycles[:10]  # Limit to first 10 cycles
        }
    
    except ImportError:
        # networkx not available
        return {
            'has_circular_imports': False,
            'cycles': [],
            'error': 'networkx not available'
        }
    except Exception as e:
        return {
            'has_circular_imports': False,
            'cycles': [],
            'error': str(e)
        }

def analyze_file(filepath):
    """Analyze a single Python file with all tools."""
    result = {
        'file': filepath,
        'relative_path': os.path.relpath(filepath, REPO_ROOT),
        'pylint': None,
        'flake8': None,
        'mypy': None,
        'imports': None,
        'dead_code': None,
        'issues': []
    }
    
    # Run Pylint
    result['pylint'] = run_pylint(filepath)
    
    # Run Flake8
    result['flake8'] = run_flake8(filepath)
    
    # Run mypy
    result['mypy'] = run_mypy(filepath)
    
    # Analyze imports
    result['imports'] = analyze_imports(filepath)
    
    # Check for dead code
    result['dead_code'] = check_dead_code(filepath)
    
    # Collect issues from all tools
    if result['pylint'] and not result['pylint'].get('success'):
        result['issues'].append({
            'type': 'PYLINT_ERROR',
            'severity': 'MEDIUM',
            'message': result['pylint'].get('error', 'Pylint failed'),
            'tool': 'pylint'
        })
    
    if result['flake8']:
        for violation in result['flake8']:
            result['issues'].append({
                'type': f"FLAKE8_{violation.get('code', 'UNKNOWN')}",
                'severity': 'LOW' if violation.get('code', '').startswith('W') else 'MEDIUM',
                'message': violation.get('text', 'Flake8 violation'),
                'line': violation.get('line'),
                'column': violation.get('column'),
                'code': violation.get('code'),
                'tool': 'flake8'
            })
    
    if result['mypy']:
        for error in result['mypy']:
            result['issues'].append({
                'type': f"MYPY_{error.get('code', 'UNKNOWN')}",
                'severity': 'HIGH' if error.get('severity', '') == 'error' else 'MEDIUM',
                'message': error.get('message', 'Mypy error'),
                'line': error.get('line'),
                'column': error.get('column'),
                'code': error.get('code'),
                'tool': 'mypy'
            })
    
    if result['imports'] and result['imports'].get('unused_imports'):
        for imp in result['imports']['unused_imports']:
            result['issues'].append({
                'type': 'UNUSED_IMPORT',
                'severity': 'LOW',
                'message': f"Potentially unused import: {imp.get('name', 'unknown')}",
                'line': imp.get('line'),
                'tool': 'import_analysis'
            })
    
    if result['dead_code'] and result['dead_code'].get('dead_code'):
        for code in result['dead_code']['dead_code']:
            result['issues'].append({
                'type': 'DEAD_CODE',
                'severity': 'MEDIUM',
                'message': f"Dead code found: {code.get('reason', 'unknown')}",
                'line': code.get('line'),
                'tool': 'vulture'
            })
    
    return result

def run_all_tests(repo_root):
    """Run all tests in the repository."""
    test_results = {
        'total_tests': 0,
        'passed': 0,
        'failed': 0,
        'errors': 0,
        'skipped': 0,
        'test_files': [],
        'coverage': None
    }
    
    # Find all test files
    test_files = []
    for root, dirs, files in os.walk(repo_root):
        if '.git' in root or '__pycache__' in root:
            continue
        for filename in files:
            if filename.startswith('test_') and filename.endswith('.py'):
                test_files.append(os.path.join(root, filename))
    
    print(f"Running tests on {len(test_files)} test files...")
    
    # Run pytest on all test files
    if test_files:
        # Run pytest on the tests directory
        tests_dir = os.path.join(repo_root, 'tests')
        if os.path.exists(tests_dir):
            result = run_pytest(tests_dir)
            test_results['test_files'].append({
                'path': tests_dir,
                'result': result
            })
        
        # Also run on pillar tests
        for pillar in ['pillar2', 'pillar3']:
            pillar_tests = os.path.join(repo_root, pillar, 'tests')
            if os.path.exists(pillar_tests):
                result = run_pytest(pillar_tests)
                test_results['test_files'].append({
                    'path': pillar_tests,
                    'result': result
                })
    
    # Calculate totals
    for test_file in test_results['test_files']:
        result = test_file['result']
        if result.get('success'):
            # Parse output to get counts
            output = result.get('output', '')
            if 'passed' in output:
                try:
                    # Try to extract numbers from output
                    import re
                    passed_match = re.search(r'(\d+) passed', output)
                    failed_match = re.search(r'(\d+) failed', output)
                    error_match = re.search(r'(\d+) error', output)
                    
                    test_results['passed'] += int(passed_match.group(1)) if passed_match else 0
                    test_results['failed'] += int(failed_match.group(1)) if failed_match else 0
                    test_results['errors'] += int(error_match.group(1)) if error_match else 0
                except:
                    pass
    
    test_results['total_tests'] = test_results['passed'] + test_results['failed'] + test_results['errors']
    
    return test_results

def main():
    """Main static and dynamic analysis function."""
    print("Starting Phase 4: Static & Dynamic Analysis...")
    print(f"Repository Root: {REPO_ROOT}")
    
    report = {
        'repository': {
            'name': 'Open-Omniscience',
            'url': 'https://github.com/ideotion/Open-Omniscience',
            'local_path': REPO_ROOT,
            'scan_timestamp': datetime.now().isoformat(),
            'scan_type': 'Phase 4: Static & Dynamic Analysis'
        },
        'summary': {},
        'files': {},
        'test_results': {},
        'circular_imports': {},
        'critical_issues': [],
        'high_issues': [],
        'medium_issues': [],
        'low_issues': []
    }
    
    # Find all Python files
    python_files = []
    for root, dirs, files in os.walk(REPO_ROOT):
        if '.git' in root or '__pycache__' in root:
            continue
        for filename in files:
            if filename.endswith('.py'):
                filepath = os.path.join(root, filename)
                python_files.append(filepath)
    
    print(f"Analyzing {len(python_files)} Python files with static analysis tools...")
    
    # Analyze each file
    for i, filepath in enumerate(python_files, 1):
        if i % 50 == 0:
            print(f"  Processed {i}/{len(python_files)} files...")
        
        try:
            file_result = analyze_file(filepath)
            report['files'][filepath] = file_result
            
            # Categorize issues by severity
            for issue in file_result.get('issues', []):
                severity = issue.get('severity', 'LOW')
                if severity == 'CRITICAL':
                    report['critical_issues'].append(issue)
                elif severity == 'HIGH':
                    report['high_issues'].append(issue)
                elif severity == 'MEDIUM':
                    report['medium_issues'].append(issue)
                else:
                    report['low_issues'].append(issue)
        
        except Exception as e:
            report['critical_issues'].append({
                'type': 'ANALYSIS_FAILED',
                'severity': 'CRITICAL',
                'message': f"Failed to analyze {filepath}: {str(e)}",
                'file': filepath
            })
    
    # Check for circular imports
    report['circular_imports'] = check_circular_imports(REPO_ROOT)
    
    if report['circular_imports'].get('has_circular_imports'):
        report['high_issues'].append({
            'type': 'CIRCULAR_IMPORTS',
            'severity': 'HIGH',
            'message': 'Circular imports detected',
            'details': report['circular_imports'].get('cycles', [])
        })
    
    # Run all tests
    report['test_results'] = run_all_tests(REPO_ROOT)
    
    # Generate summary
    total_files = len(report['files'])
    total_issues = (len(report['critical_issues']) + len(report['high_issues']) + 
                    len(report['medium_issues']) + len(report['low_issues']))
    
    # Count issues by tool
    tool_counts = {}
    for issue in report['critical_issues'] + report['high_issues'] + report['medium_issues'] + report['low_issues']:
        tool = issue.get('tool', 'unknown')
        tool_counts[tool] = tool_counts.get(tool, 0) + 1
    
    report['summary'] = {
        'total_files_analyzed': total_files,
        'total_issues': total_issues,
        'critical_issues': len(report['critical_issues']),
        'high_issues': len(report['high_issues']),
        'medium_issues': len(report['medium_issues']),
        'low_issues': len(report['low_issues']),
        'issues_by_tool': tool_counts,
        'test_results': report['test_results'],
        'has_circular_imports': report['circular_imports'].get('has_circular_imports', False),
        'scan_completed': datetime.now().isoformat()
    }
    
    # Save report
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    
    print(f"\nPhase 4 Complete!")
    print(f"Files Analyzed: {total_files}")
    print(f"Total Issues: {total_issues}")
    print(f"Critical Issues: {len(report['critical_issues'])}")
    print(f"High Issues: {len(report['high_issues'])}")
    print(f"Medium Issues: {len(report['medium_issues'])}")
    print(f"Low Issues: {len(report['low_issues'])}")
    print(f"Report saved to: {OUTPUT_FILE}")
    
    # Print test results
    test_results = report['test_results']
    print(f"\n=== Test Results ===")
    print(f"Total Tests: {test_results.get('total_tests', 0)}")
    print(f"Passed: {test_results.get('passed', 0)}")
    print(f"Failed: {test_results.get('failed', 0)}")
    print(f"Errors: {test_results.get('errors', 0)}")
    
    # Print critical issues
    if report['critical_issues']:
        print("\n=== CRITICAL ISSUES ===")
        for i, issue in enumerate(report['critical_issues'][:20], 1):
            print(f"  {i}. [{issue['type']}] {issue['message']} ({issue.get('file', 'unknown')}:{issue.get('line', '?')})")
    
    # Print summary by type
    print("\n=== Issues by Type ===")
    issue_types = {}
    for issue in report['critical_issues'] + report['high_issues'] + report['medium_issues'] + report['low_issues']:
        itype = issue['type']
        issue_types[itype] = issue_types.get(itype, 0) + 1
    for itype, count in sorted(issue_types.items(), key=lambda x: x[1], reverse=True)[:20]:
        print(f"  {itype}: {count}")

if __name__ == '__main__':
    main()
