#!/usr/bin/env python3
"""
Open-Omniscience Qubes Branch - PHASE 1: RECURSIVE CODEBASE MAPPING
================================================================

This script performs EXHAUSTIVE recursive mapping of the entire codebase
in the 0.02_Qubes branch, following the 7-phase debugging protocol.

RULES:
- NEVER SKIP any file or directory
- ALWAYS VERIFY every reference
- DOCUMENT EVERYTHING
- RECURSE ALWAYS

Output: Complete JSON map of all files with metadata for traceability
"""

import os
import hashlib
import json
import stat
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
import argparse


class FileMapper:
    """Recursive file system mapper with exhaustive verification."""
    
    def __init__(self, root_path: str, exclude_patterns: Optional[List[str]] = None):
        """
        Initialize the file mapper.
        
        Args:
            root_path: Root directory to start mapping from
            exclude_patterns: Patterns to exclude (e.g., ['.git', '__pycache__'])
        """
        self.root_path = os.path.abspath(root_path)
        self.exclude_patterns = exclude_patterns or ['.git', '__pycache__', '.pytest_cache', 'node_modules', '.venv', 'venv', '*.pyc', '*.swp', '*.swo']
        self.file_map: Dict[str, Any] = {
            'metadata': {
                'start_time': datetime.now().isoformat(),
                'root_path': self.root_path,
                'protocol': '7-Phase Debugging Protocol - Phase 1',
                'branch': '0.02_Qubes'
            },
            'directories': {},
            'files': {},
            'stats': {
                'total_directories': 0,
                'total_files': 0,
                'total_size_bytes': 0,
                'total_size_human': '',
                'file_types': {},
                'largest_file': {'path': '', 'size': 0},
                'smallest_file': {'path': '', 'size': float('inf')}
            }
        }
        self.errors: List[Dict[str, Any]] = []
        self.warnings: List[Dict[str, Any]] = []
    
    def is_excluded(self, path: str) -> bool:
        """Check if a path should be excluded from mapping."""
        for pattern in self.exclude_patterns:
            if pattern in path:
                return True
        return False
    
    def get_file_type(self, filepath: str) -> str:
        """Determine file type based on extension."""
        if os.path.isdir(filepath):
            return 'directory'
        
        ext = os.path.splitext(filepath)[1].lower()
        
        type_map = {
            '.py': 'python',
            '.sh': 'shell',
            '.bash': 'shell',
            '.zsh': 'shell',
            '.json': 'json',
            '.yaml': 'yaml',
            '.yml': 'yaml',
            '.toml': 'toml',
            '.md': 'markdown',
            '.txt': 'text',
            '.cfg': 'config',
            '.conf': 'config',
            '.ini': 'config',
            '.env': 'env',
            '.html': 'html',
            '.css': 'css',
            '.js': 'javascript',
            '.ts': 'typescript',
            '.sql': 'sql',
            '.gitignore': 'gitignore',
            '.dockerignore': 'dockerignore',
            'Dockerfile': 'dockerfile',
            'Makefile': 'makefile',
            'requirements.txt': 'requirements',
            'setup.py': 'setup',
            '': 'unknown'
        }
        
        return type_map.get(ext, type_map.get(os.path.basename(filepath), 'unknown'))
    
    def calculate_hash(self, filepath: str, hash_algo: str = 'sha256') -> str:
        """Calculate file hash for traceability."""
        try:
            hash_func = getattr(hashlib, hash_algo)()
            with open(filepath, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    hash_func.update(chunk)
            return hash_func.hexdigest()
        except Exception as e:
            self.errors.append({
                'type': 'hash_error',
                'path': filepath,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            })
            return 'ERROR'
    
    def get_file_stats(self, filepath: str) -> Dict[str, Any]:
        """Get comprehensive file statistics."""
        try:
            st = os.stat(filepath)
            return {
                'size_bytes': st.st_size,
                'size_human': self.format_size(st.st_size),
                'created': datetime.fromtimestamp(st.st_ctime).isoformat(),
                'modified': datetime.fromtimestamp(st.st_mtime).isoformat(),
                'accessed': datetime.fromtimestamp(st.st_atime).isoformat(),
                'mode': oct(st.st_mode),
                'mode_human': stat.filemode(st.st_mode),
                'uid': st.st_uid,
                'gid': st.st_gid,
                'nlink': st.st_nlink,
                'inode': st.st_ino
            }
        except Exception as e:
            self.errors.append({
                'type': 'stat_error',
                'path': filepath,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            })
            return {}
    
    def format_size(self, size_bytes: int) -> str:
        """Format size in human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"
    
    def map_directory(self, dirpath: str) -> Dict[str, Any]:
        """Recursively map a directory and all its contents."""
        dirpath = os.path.abspath(dirpath)
        
        # Skip excluded directories
        if self.is_excluded(dirpath):
            self.warnings.append({
                'type': 'excluded',
                'path': dirpath,
                'message': 'Directory excluded from mapping',
                'timestamp': datetime.now().isoformat()
            })
            return {}
        
        dir_info: Dict[str, Any] = {
            'path': dirpath,
            'relative_path': os.path.relpath(dirpath, self.root_path),
            'contents': {
                'directories': [],
                'files': []
            },
            'stats': self.get_file_stats(dirpath)
        }
        
        try:
            with os.scandir(dirpath) as entries:
                for entry in entries:
                    full_path = entry.path
                    relative_path = os.path.relpath(full_path, self.root_path)
                    
                    if entry.is_dir():
                        if not self.is_excluded(full_path):
                            dir_info['contents']['directories'].append(relative_path)
                            # Recursively map subdirectory
                            subdir_info = self.map_directory(full_path)
                            if subdir_info:
                                self.file_map['directories'][relative_path] = subdir_info
                    elif entry.is_file():
                        if not self.is_excluded(full_path):
                            dir_info['contents']['files'].append(relative_path)
                            # Map file
                            file_info = self.map_file(full_path)
                            if file_info:
                                self.file_map['files'][relative_path] = file_info
        
        except PermissionError as e:
            self.errors.append({
                'type': 'permission_error',
                'path': dirpath,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            self.errors.append({
                'type': 'scan_error',
                'path': dirpath,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            })
        
        return dir_info
    
    def map_file(self, filepath: str) -> Dict[str, Any]:
        """Map a single file with all metadata."""
        filepath = os.path.abspath(filepath)
        relative_path = os.path.relpath(filepath, self.root_path)
        
        # Skip excluded files
        if self.is_excluded(filepath):
            return {}
        
        file_type = self.get_file_type(filepath)
        
        file_info: Dict[str, Any] = {
            'path': filepath,
            'relative_path': relative_path,
            'filename': os.path.basename(filepath),
            'directory': os.path.dirname(relative_path),
            'type': file_type,
            'extension': os.path.splitext(filepath)[1].lower() if os.path.splitext(filepath)[1] else '',
            'stats': self.get_file_stats(filepath),
            'hashes': {
                'sha256': self.calculate_hash(filepath, 'sha256'),
                'md5': self.calculate_hash(filepath, 'md5')
            }
        }
        
        # Update statistics
        self.file_map['stats']['total_files'] += 1
        size = file_info['stats'].get('size_bytes', 0)
        self.file_map['stats']['total_size_bytes'] += size
        
        # Track file types
        if file_type not in self.file_map['stats']['file_types']:
            self.file_map['stats']['file_types'][file_type] = 0
        self.file_map['stats']['file_types'][file_type] += 1
        
        # Track largest/smallest files
        if size > self.file_map['stats']['largest_file']['size']:
            self.file_map['stats']['largest_file'] = {'path': relative_path, 'size': size}
        if size < self.file_map['stats']['smallest_file']['size'] and size > 0:
            self.file_map['stats']['smallest_file'] = {'path': relative_path, 'size': size}
        
        return file_info
    
    def run(self) -> Dict[str, Any]:
        """Run the complete mapping process."""
        print(f"\n{'='*80}")
        print(f"PHASE 1: RECURSIVE CODEBASE MAPPING")
        print(f"{'='*80}")
        print(f"Root Path: {self.root_path}")
        print(f"Start Time: {datetime.now().isoformat()}")
        print(f"Branch: 0.02_Qubes")
        print(f"{'='*80}\n")
        
        # Map the root directory
        print(f"Mapping root directory: {self.root_path}")
        root_info = self.map_directory(self.root_path)
        
        # Update directory count
        self.file_map['stats']['total_directories'] = len(self.file_map['directories'])
        self.file_map['stats']['total_size_human'] = self.format_size(self.file_map['stats']['total_size_bytes'])
        
        # Add root info
        self.file_map['root'] = root_info
        
        # Finalize
        self.file_map['metadata']['end_time'] = datetime.now().isoformat()
        self.file_map['metadata']['duration_seconds'] = (
            datetime.fromisoformat(self.file_map['metadata']['end_time']) - 
            datetime.fromisoformat(self.file_map['metadata']['start_time'])
        ).total_seconds()
        
        # Add error and warning counts
        self.file_map['metadata']['error_count'] = len(self.errors)
        self.file_map['metadata']['warning_count'] = len(self.warnings)
        
        # Print summary
        print(f"\n{'='*80}")
        print(f"PHASE 1 SUMMARY")
        print(f"{'='*80}")
        print(f"Total Directories: {self.file_map['stats']['total_directories']}")
        print(f"Total Files: {self.file_map['stats']['total_files']}")
        print(f"Total Size: {self.file_map['stats']['total_size_human']}")
        print(f"File Types: {len(self.file_map['stats']['file_types'])}")
        print(f"Largest File: {self.file_map['stats']['largest_file']['path']} ({self.format_size(self.file_map['stats']['largest_file']['size'])})")
        print(f"Smallest File: {self.file_map['stats']['smallest_file']['path']} ({self.format_size(self.file_map['stats']['smallest_file']['size'])})")
        print(f"Errors: {len(self.errors)}")
        print(f"Warnings: {len(self.warnings)}")
        print(f"Duration: {self.file_map['metadata']['duration_seconds']:.2f} seconds")
        print(f"{'='*80}\n")
        
        # Print file types
        print("File Type Distribution:")
        for file_type, count in sorted(self.file_map['stats']['file_types'].items(), key=lambda x: x[1], reverse=True):
            print(f"  {file_type:20s}: {count:4d} files")
        print()
        
        # Print errors if any
        if self.errors:
            print(f"\n{'='*80}")
            print(f"ERRORS ({len(self.errors)})")
            print(f"{'='*80}")
            for error in self.errors:
                print(f"  [{error['type']}] {error['path']}: {error['error']}")
        
        # Print warnings if any
        if self.warnings:
            print(f"\n{'='*80}")
            print(f"WARNINGS ({len(self.warnings)})")
            print(f"{'='*80}")
            for warning in self.warnings[:10]:  # Limit to first 10
                print(f"  [{warning['type']}] {warning['path']}: {warning['message']}")
            if len(self.warnings) > 10:
                print(f"  ... and {len(self.warnings) - 10} more warnings")
        
        return self.file_map
    
    def save_report(self, output_path: str) -> None:
        """Save the mapping report to a JSON file."""
        with open(output_path, 'w') as f:
            json.dump(self.file_map, f, indent=2, default=str)
        print(f"\nReport saved to: {output_path}")
        print(f"Report size: {self.format_size(os.path.getsize(output_path))}")


def main():
    parser = argparse.ArgumentParser(
        description='Phase 1: Recursive Codebase Mapping for Open-Omniscience Qubes Branch'
    )
    parser.add_argument(
        '--root',
        type=str,
        default='.',
        help='Root directory to map (default: current directory)'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='QUBS_PHASE1_FULL_REPORT.json',
        help='Output JSON file path (default: QUBS_PHASE1_FULL_REPORT.json)'
    )
    parser.add_argument(
        '--exclude',
        type=str,
        nargs='*',
        default=[],
        help='Additional patterns to exclude'
    )
    
    args = parser.parse_args()
    
    # Initialize mapper
    exclude_patterns = ['.git', '__pycache__', '.pytest_cache', 'node_modules', '.venv', 'venv'] + args.exclude
    mapper = FileMapper(args.root, exclude_patterns)
    
    # Run mapping
    result = mapper.run()
    
    # Save report
    mapper.save_report(args.output)
    
    print(f"\n{'='*80}")
    print(f"PHASE 1 COMPLETE")
    print(f"{'='*80}")
    print(f"Next Step: Proceed to PHASE 2 - Dependency & Link Verification")
    print(f"Command: python3 qubes_phase2_dependency_checker.py --input {args.output}")
    print(f"{'='*80}\n")


if __name__ == '__main__':
    main()
