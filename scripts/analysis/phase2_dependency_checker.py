#!/usr/bin/env python3
"""
Phase 2: Dependency & Link Verification
Extracts all references (imports, paths, URLs, configs) from every file,
verifies their existence/compatibility, and builds a dependency graph.
"""

import ast
import json
import os
import re
from datetime import datetime
from urllib.parse import urlparse

REPO_ROOT = "/workspace/ideotion__Open-Omniscience"
OUTPUT_FILE = "/workspace/ideotion__Open-Omniscience/PHASE2_REPORT.json"

def extract_python_imports(filepath):
    """Extract all imports from a Python file."""
    imports = {
        'imports': [],
        'from_imports': [],
        'relative_imports': [],
        'errors': []
    }
    
    try:
        with open(filepath, encoding='utf-8') as f:
            content = f.read()
        
        tree = ast.parse(content, filename=filepath)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports['imports'].append({
                        'module': alias.name,
                        'asname': alias.asname,
                        'line': node.lineno,
                        'source': filepath
                    })
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                level = node.level
                for alias in node.names:
                    import_data = {
                        'module': module,
                        'name': alias.name,
                        'asname': alias.asname,
                        'line': node.lineno,
                        'source': filepath
                    }
                    if level > 0:
                        imports['relative_imports'].append(import_data)
                        import_data['level'] = level
                    else:
                        imports['from_imports'].append(import_data)
    
    except SyntaxError as e:
        imports['errors'].append({
            'type': 'syntax_error',
            'message': str(e),
            'line': e.lineno,
            'file': filepath
        })
    except Exception as e:
        imports['errors'].append({
            'type': 'parse_error',
            'message': str(e),
            'file': filepath
        })
    
    return imports

def extract_file_references(filepath):
    """Extract file path references from any file."""
    references = {
        'file_paths': [],
        'directory_paths': [],
        'urls': [],
        'emails': [],
        'config_refs': [],
        'errors': []
    }
    
    try:
        with open(filepath, encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # Extract file paths (quoted strings that look like paths)
        path_pattern = r'(?:\"|\')([a-zA-Z]:?[\\/][^\"\'\s]*(?:\.\w+)?)'
        for match in re.finditer(path_pattern, content):
            path = match.group(1)
            if not path.startswith('http') and not path.startswith('//'):
                if os.path.isabs(path) or '/' in path or '\\' in path:
                    references['file_paths'].append({
                        'path': path,
                        'line': content[:match.start()].count('\n') + 1,
                        'source': filepath
                    })
        
        # Extract directory paths
        dir_pattern = r'(?:\"|\')([a-zA-Z]:?[\\/][^\"\'\s]*(?:[\\/]|$))'
        for match in re.finditer(dir_pattern, content):
            path = match.group(1)
            if not path.startswith('http') and not path.startswith('//'):
                if path.endswith('/') or path.endswith('\\'):
                    references['directory_paths'].append({
                        'path': path,
                        'line': content[:match.start()].count('\n') + 1,
                        'source': filepath
                    })
        
        # Extract URLs
        url_pattern = r'https?://[^\s\"\']+|www\.[^\s\"\']+'
        for match in re.finditer(url_pattern, content):
            url = match.group(0)
            references['urls'].append({
                'url': url,
                'line': content[:match.start()].count('\n') + 1,
                'source': filepath
            })
        
        # Extract emails
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        for match in re.finditer(email_pattern, content):
            email = match.group(0)
            references['emails'].append({
                'email': email,
                'line': content[:match.start()].count('\n') + 1,
                'source': filepath
            })
        
        # Extract config file references
        config_extensions = ['.yml', '.yaml', '.json', '.cfg', '.conf', '.ini', '.toml']
        for ext in config_extensions:
            config_pattern = rf'[\"\']([^\"\']+{re.escape(ext)})[\"\']'
            for match in re.finditer(config_pattern, content):
                config_file = match.group(1)
                references['config_refs'].append({
                    'config': config_file,
                    'line': content[:match.start()].count('\n') + 1,
                    'source': filepath
                })
    
    except Exception as e:
        references['errors'].append({
            'type': 'read_error',
            'message': str(e),
            'file': filepath
        })
    
    return references

def verify_reference(reference, ref_type, repo_root):
    """Verify if a reference exists and is accessible."""
    result = {
        'reference': reference,
        'type': ref_type,
        'exists': False,
        'accessible': False,
        'resolved_path': None,
        'error': None,
        'status': 'UNKNOWN'
    }
    
    try:
        if ref_type in ['file_paths', 'directory_paths', 'config_refs']:
            # Handle relative paths
            if not os.path.isabs(reference):
                # Try to resolve from repo root
                test_path = os.path.join(repo_root, reference)
                if os.path.exists(test_path):
                    result['resolved_path'] = test_path
                    result['exists'] = True
                    result['accessible'] = os.access(test_path, os.R_OK)
                    result['status'] = 'OK'
                else:
                    # Try relative to source file directory
                    result['status'] = 'MISSING'
                    result['error'] = f"Path not found: {reference}"
            else:
                if os.path.exists(reference):
                    result['resolved_path'] = reference
                    result['exists'] = True
                    result['accessible'] = os.access(reference, os.R_OK)
                    result['status'] = 'OK'
                else:
                    result['status'] = 'MISSING'
                    result['error'] = f"Path not found: {reference}"
        
        elif ref_type == 'urls':
            # For URLs, just check if they're well-formed
            parsed = urlparse(reference)
            if parsed.scheme and parsed.netloc:
                result['status'] = 'WELL_FORMED'
                result['exists'] = True  # We can't verify remote URLs
            else:
                result['status'] = 'MALFORMED_URL'
                result['error'] = f"Malformed URL: {reference}"
        
        elif ref_type == 'imports' or ref_type == 'from_imports':
            # For Python imports, try to import the module
            try:
                # Skip relative imports for now
                if reference.startswith('.'):
                    result['status'] = 'RELATIVE_IMPORT'
                    result['exists'] = True
                else:
                    # Try to import
                    __import__(reference)
                    result['status'] = 'IMPORTABLE'
                    result['exists'] = True
            except ImportError as e:
                result['status'] = 'IMPORT_ERROR'
                result['error'] = str(e)
            except Exception as e:
                result['status'] = 'IMPORT_FAILED'
                result['error'] = str(e)
    
    except Exception as e:
        result['status'] = 'VERIFICATION_ERROR'
        result['error'] = str(e)
    
    return result

def verify_python_imports(imports_data, repo_root):
    """Verify Python imports."""
    results = []
    
    for imp in imports_data['imports']:
        result = verify_reference(imp['module'], 'imports', repo_root)
        result['import_type'] = 'import'
        result['module'] = imp['module']
        result['asname'] = imp.get('asname')
        result['line'] = imp['line']
        result['source'] = imp['source']
        results.append(result)
    
    for imp in imports_data['from_imports']:
        result = verify_reference(imp['module'], 'from_imports', repo_root)
        result['import_type'] = 'from_import'
        result['module'] = imp['module']
        result['name'] = imp['name']
        result['asname'] = imp.get('asname')
        result['line'] = imp['line']
        result['source'] = imp['source']
        results.append(result)
    
    for imp in imports_data['relative_imports']:
        result = {
            'reference': imp['module'],
            'type': 'relative_imports',
            'import_type': 'relative_import',
            'module': imp['module'],
            'name': imp.get('name'),
            'asname': imp.get('asname'),
            'level': imp.get('level', 0),
            'line': imp['line'],
            'source': imp['source'],
            'exists': True,  # Can't easily verify relative imports
            'accessible': True,
            'resolved_path': None,
            'error': None,
            'status': 'RELATIVE_IMPORT'
        }
        results.append(result)
    
    return results

def build_dependency_graph(files_data, repo_root):
    """Build a dependency graph from all references."""
    graph = {
        'nodes': set(),
        'edges': [],
        'dependencies': {},
        'dependents': {}
    }
    
    # Add all files as nodes
    for filepath in files_data.keys():
        rel_path = os.path.relpath(filepath, repo_root)
        graph['nodes'].add(rel_path)
        graph['dependencies'][rel_path] = set()
        graph['dependents'][rel_path] = set()
    
    # Process all references to build edges
    for filepath, data in files_data.items():
        rel_source = os.path.relpath(filepath, repo_root)
        
        # Process Python imports
        if 'python_imports' in data and data['python_imports']:
            for imp in data['python_imports'].get('imports', []) + data['python_imports'].get('from_imports', []) + data['python_imports'].get('relative_imports', []):
                status = imp.get('status', 'UNKNOWN')
                if status in ['OK', 'IMPORTABLE', 'RELATIVE_IMPORT']:
                    target = imp.get('module', imp.get('reference', ''))
                    if target:
                        graph['edges'].append({
                            'source': rel_source,
                            'target': target,
                            'type': 'import',
                            'status': status
                        })
                        graph['dependencies'][rel_source].add(target)
                        if target not in graph['dependents']:
                            graph['dependents'][target] = set()
                        graph['dependents'][target].add(rel_source)
        
        # Process file references
        if 'file_references' in data and data['file_references']:
            for ref in data['file_references'].get('file_paths', []):
                if ref.get('status') == 'OK' or (isinstance(ref, dict) and 'path' in ref):
                    target = ref.get('path', '')
                    if target:
                        graph['edges'].append({
                            'source': rel_source,
                            'target': target,
                            'type': 'file_reference',
                            'status': 'OK'
                        })
                        graph['dependencies'][rel_source].add(target)
                        if target not in graph['dependents']:
                            graph['dependents'][target] = set()
                        graph['dependents'][target].add(rel_source)
    
    return graph

def scan_file(filepath, repo_root):
    """Scan a single file for all references."""
    result = {
        'file': filepath,
        'relative_path': os.path.relpath(filepath, repo_root),
        'file_type': get_file_type(filepath),
        'python_imports': None,
        'file_references': None,
        'verification_results': {
            'imports': [],
            'references': []
        },
        'issues': []
    }
    
    # Extract based on file type
    if filepath.endswith('.py'):
        result['python_imports'] = extract_python_imports(filepath)
        result['file_references'] = extract_file_references(filepath)
        
        # Verify imports
        if result['python_imports']:
            result['verification_results']['imports'] = verify_python_imports(
                result['python_imports'], repo_root
            )
            
            # Check for import errors
            for imp in result['python_imports'].get('errors', []):
                result['issues'].append({
                    'type': 'IMPORT_PARSE_ERROR',
                    'severity': 'CRITICAL',
                    'message': imp['message'],
                    'line': imp.get('line'),
                    'file': filepath
                })
        
        # Verify file references
        if result['file_references']:
            for ref_type in ['file_paths', 'directory_paths', 'config_refs']:
                for ref in result['file_references'].get(ref_type, []):
                    verification = verify_reference(ref['path'], ref_type, repo_root)
                    result['verification_results']['references'].append(verification)
                    
                    if verification['status'] != 'OK':
                        result['issues'].append({
                            'type': 'BROKEN_REFERENCE',
                            'severity': 'CRITICAL' if ref_type == 'config_refs' else 'HIGH',
                            'message': f"{ref_type.replace('_', ' ').title()} not found: {ref['path']}",
                            'line': ref['line'],
                            'file': filepath,
                            'reference_type': ref_type,
                            'reference': ref['path']
                        })
    else:
        # For non-Python files, just extract references
        result['file_references'] = extract_file_references(filepath)
        
        if result['file_references']:
            for ref_type in ['file_paths', 'directory_paths', 'config_refs']:
                for ref in result['file_references'].get(ref_type, []):
                    verification = verify_reference(ref['path'], ref_type, repo_root)
                    result['verification_results']['references'].append(verification)
                    
                    if verification['status'] != 'OK':
                        result['issues'].append({
                            'type': 'BROKEN_REFERENCE',
                            'severity': 'CRITICAL' if ref_type == 'config_refs' else 'HIGH',
                            'message': f"{ref_type.replace('_', ' ').title()} not found: {ref['path']}",
                            'line': ref['line'],
                            'file': filepath,
                            'reference_type': ref_type,
                            'reference': ref['path']
                        })
    
    # Check for URL issues
    if result['file_references']:
        for url_ref in result['file_references'].get('urls', []):
            verification = verify_reference(url_ref['url'], 'urls', repo_root)
            if verification['status'] != 'WELL_FORMED':
                result['issues'].append({
                    'type': 'BROKEN_URL',
                    'severity': 'MEDIUM',
                    'message': f"Malformed URL: {url_ref['url']}",
                    'line': url_ref['line'],
                    'file': filepath,
                    'url': url_ref['url']
                })
    
    return result

def get_file_type(filepath):
    """Determine file type."""
    if filepath.endswith('.py'):
        return 'Python'
    elif filepath.endswith('.md'):
        return 'Markdown'
    elif filepath.endswith('.txt'):
        return 'Text'
    elif filepath.endswith('.yml') or filepath.endswith('.yaml'):
        return 'YAML'
    elif filepath.endswith('.json'):
        return 'JSON'
    elif filepath.endswith('.sh'):
        return 'Shell Script'
    elif filepath.endswith('.conf') or filepath.endswith('.cfg'):
        return 'Configuration'
    elif filepath.endswith('.ini'):
        return 'INI'
    elif filepath.endswith('.toml'):
        return 'TOML'
    elif filepath.endswith('.svg'):
        return 'SVG'
    elif filepath.endswith('.html'):
        return 'HTML'
    elif filepath.endswith('.js'):
        return 'JavaScript'
    elif filepath.endswith('.css'):
        return 'CSS'
    else:
        return 'Other'

def main():
    """Main dependency verification function."""
    print("Starting Phase 2: Dependency & Link Verification...")
    print(f"Repository Root: {REPO_ROOT}")
    
    report = {
        'repository': {
            'name': 'Open-Omniscience',
            'url': 'https://github.com/ideotion/Open-Omniscience',
            'local_path': REPO_ROOT,
            'scan_timestamp': datetime.now().isoformat(),
            'scan_type': 'Phase 2: Dependency & Link Verification'
        },
        'summary': {},
        'files': {},
        'dependency_graph': {},
        'critical_issues': [],
        'all_issues': []
    }
    
    # Scan all Python files and other relevant files
    files_to_scan = []
    for root, dirs, files in os.walk(REPO_ROOT):
        if '.git' in root:
            continue
        for filename in files:
            filepath = os.path.join(root, filename)
            # Scan Python files and config files
            if (filename.endswith('.py') or 
                filename.endswith('.yml') or 
                filename.endswith('.yaml') or 
                filename.endswith('.json') or
                filename.endswith('.md') or
                filename.endswith('.txt') or
                filename.endswith('.sh') or
                filename.endswith('.ini') or
                filename.endswith('.toml') or
                filename.endswith('.conf') or
                filename.endswith('.cfg')):
                files_to_scan.append(filepath)
    
    print(f"Scanning {len(files_to_scan)} files for dependencies and references...")
    
    # Scan each file
    for i, filepath in enumerate(files_to_scan, 1):
        if i % 50 == 0:
            print(f"  Processed {i}/{len(files_to_scan)} files...")
        
        try:
            file_result = scan_file(filepath, REPO_ROOT)
            report['files'][filepath] = file_result
            
            # Collect issues
            for issue in file_result.get('issues', []):
                report['all_issues'].append(issue)
                if issue['severity'] in ['CRITICAL', 'HIGH']:
                    report['critical_issues'].append(issue)
        
        except Exception as e:
            report['all_issues'].append({
                'type': 'SCAN_ERROR',
                'severity': 'CRITICAL',
                'message': str(e),
                'file': filepath
            })
    
    # Build dependency graph
    report['dependency_graph'] = build_dependency_graph(report['files'], REPO_ROOT)
    
    # Generate summary
    total_files = len(report['files'])
    total_issues = len(report['all_issues'])
    critical_issues = len(report['critical_issues'])
    total_imports = sum(
        (len(f.get('python_imports', {}).get('imports', [])) if f.get('python_imports') else 0) +
        (len(f.get('python_imports', {}).get('from_imports', [])) if f.get('python_imports') else 0) +
        (len(f.get('python_imports', {}).get('relative_imports', [])) if f.get('python_imports') else 0)
        for f in report['files'].values()
    )
    total_references = sum(
        (len(f.get('file_references', {}).get('file_paths', [])) if f.get('file_references') else 0) +
        (len(f.get('file_references', {}).get('directory_paths', [])) if f.get('file_references') else 0) +
        (len(f.get('file_references', {}).get('urls', [])) if f.get('file_references') else 0) +
        (len(f.get('file_references', {}).get('config_refs', [])) if f.get('file_references') else 0)
        for f in report['files'].values()
    )
    
    report['summary'] = {
        'total_files_scanned': total_files,
        'total_imports_found': total_imports,
        'total_references_found': total_references,
        'total_issues': total_issues,
        'critical_issues': critical_issues,
        'high_issues': len([i for i in report['all_issues'] if i['severity'] == 'HIGH']),
        'medium_issues': len([i for i in report['all_issues'] if i['severity'] == 'MEDIUM']),
        'low_issues': len([i for i in report['all_issues'] if i['severity'] == 'LOW']),
        'scan_completed': datetime.now().isoformat()
    }
    
    # Save report
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    
    print("\nPhase 2 Complete!")
    print(f"Files Scanned: {total_files}")
    print(f"Imports Found: {total_imports}")
    print(f"References Found: {total_references}")
    print(f"Total Issues: {total_issues}")
    print(f"Critical Issues: {critical_issues}")
    print(f"Report saved to: {OUTPUT_FILE}")
    
    # Print critical issues
    if report['critical_issues']:
        print("\n=== CRITICAL ISSUES ===")
        for i, issue in enumerate(report['critical_issues'][:20], 1):
            print(f"  {i}. [{issue['type']}] {issue['message']} ({issue['file']}:{issue.get('line', '?')})")
    
    # Print summary by type
    print("\n=== Issues by Type ===")
    issue_types = {}
    for issue in report['all_issues']:
        itype = issue['type']
        issue_types[itype] = issue_types.get(itype, 0) + 1
    for itype, count in sorted(issue_types.items(), key=lambda x: x[1], reverse=True):
        print(f"  {itype}: {count}")

if __name__ == '__main__':
    main()
