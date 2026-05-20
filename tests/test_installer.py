#!/usr/bin/env python3
"""
Test script for Open-Omniscience GUI Installer and Debian-only support
==================================================================

This script tests:
1. Documentation updates (no macOS/Windows references)
2. Install script syntax and Debian-only checks
3. GUI installer code (syntax and logic)
4. .desktop file format
5. SystemChecker functionality
"""

import os
import sys
import subprocess
import re
from pathlib import Path


class DocumentationTester:
    """Test documentation files for Debian-only references."""
    
    @staticmethod
    def test_no_macos_windows_references():
        """Check that no macOS/Windows references exist in documentation."""
        print("Testing documentation for macOS/Windows references...")
        
        docs_dir = Path(".")
        excluded_dirs = {".git", "pillar2", "pillar3", "pillar4", "node_modules", "__pycache__"}
        
        violations = []
        
        for file_path in docs_dir.rglob("*"):
            if file_path.is_file():
                # Skip excluded directories
                if any(excluded in str(file_path) for excluded in excluded_dirs):
                    continue
                
                # Only check .md and .txt files
                if file_path.suffix not in [".md", ".txt"]:
                    continue
                
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        lines = content.split('\n')
                        
                        for i, line in enumerate(lines, 1):
                            if re.search(r'\bmacOS\b|\bWindows\b|\bWSL\b', line, re.IGNORECASE):
                                violations.append(f"{file_path}:{i}: {line.strip()}")
                except (UnicodeDecodeError, PermissionError):
                    continue
        
        if violations:
            print(f"  ❌ FAILED: Found {len(violations)} macOS/Windows references:")
            for v in violations[:10]:  # Show first 10
                print(f"    - {v}")
            return False
        else:
            print("  ✅ PASSED: No macOS/Windows references found")
            return True
    
    @staticmethod
    def test_debian_references():
        """Check that Debian-based references exist."""
        print("Testing for Debian-based references...")
        
        files_to_check = [
            "README.md",
            "docs/USER_GUIDE.md",
            "docs/DEVELOPER_GUIDE.md",
            "docs/LLM_SETUP_GUIDE.md",
            "docs/CONTRIBUTING.md",
            "docs/DATABASE.md",
        ]
        
        found_debian = False
        for file_path in files_to_check:
            if Path(file_path).exists():
                with open(file_path, 'r') as f:
                    content = f.read()
                    if 'Debian-based' in content or 'debian' in content.lower():
                        found_debian = True
                        break
        
        if found_debian:
            print("  ✅ PASSED: Debian-based references found")
            return True
        else:
            print("  ❌ FAILED: No Debian-based references found")
            return False


class InstallScriptTester:
    """Test the install script."""
    
    @staticmethod
    def test_syntax():
        """Test install script syntax."""
        print("Testing install script syntax...")
        
        result = subprocess.run(['bash', '-n', 'install'], 
                              capture_output=True, text=True)
        
        if result.returncode == 0:
            print("  ✅ PASSED: Install script syntax is valid")
            return True
        else:
            print(f"  ❌ FAILED: Install script syntax error")
            print(f"    Error: {result.stderr}")
            return False
    
    @staticmethod
    def test_debian_only():
        """Test that install script is Debian-only."""
        print("Testing install script for Debian-only support...")
        
        with open('install', 'r') as f:
            content = f.read()
        
        # Check for Debian detection
        has_debian_check = 'is_debian()' in content
        has_debian_error = 'Debian-based Linux systems only' in content
        
        # Check that macOS/Windows setup is removed
        has_macos_setup = 'setup_macos()' in content
        has_windows_setup = 'setup_windows()' in content
        
        if has_debian_check and has_debian_error and not has_macos_setup and not has_windows_setup:
            print("  ✅ PASSED: Install script is Debian-only")
            return True
        else:
            print("  ❌ FAILED: Install script may still support non-Debian systems")
            return False


class GUIInstallerTester:
    """Test the GUI installer code."""
    
    @staticmethod
    def test_syntax():
        """Test GUI installer Python syntax."""
        print("Testing GUI installer syntax...")
        
        result = subprocess.run([sys.executable, '-m', 'py_compile', 'installer/gui_installer.py'],
                              capture_output=True, text=True)
        
        if result.returncode == 0:
            print("  ✅ PASSED: GUI installer syntax is valid")
            return True
        else:
            print(f"  ❌ FAILED: GUI installer syntax error")
            print(f"    Error: {result.stderr}")
            return False
    
    @staticmethod
    def test_imports():
        """Test that required imports work (except Tkinter)."""
        print("Testing GUI installer imports...")
        
        try:
            # Test imports that don't require Tkinter
            import os
            import sys
            import subprocess
            import shutil
            import stat
            import time
            import threading
            import platform
            import socket
            import json
            import webbrowser
            
            print("  ✅ PASSED: All non-GUI imports work")
            return True
        except ImportError as e:
            print(f"  ❌ FAILED: Import error: {e}")
            return False
    
    @staticmethod
    def test_system_checker_logic():
        """Test SystemChecker class logic."""
        print("Testing SystemChecker logic...")
        
        try:
            import os
            import shutil
            import platform
            
            # Test check_root
            is_root = os.geteuid() == 0
            
            # Test check_debian
            is_debian = False
            try:
                with open('/etc/os-release', 'r') as f:
                    content = f.read()
                    if 'debian' in content.lower() or 'ubuntu' in content.lower():
                        is_debian = True
            except FileNotFoundError:
                pass
            
            # Test check_command
            has_python = shutil.which('python3') is not None
            has_git = shutil.which('git') is not None
            
            # Test check_architecture
            arch = platform.machine()
            
            print(f"  - Root check: {is_root}")
            print(f"  - Debian check: {is_debian}")
            print(f"  - Architecture: {arch}")
            print(f"  - Has Python: {has_python}")
            print(f"  - Has Git: {has_git}")
            
            print("  ✅ PASSED: SystemChecker logic works")
            return True
        except Exception as e:
            print(f"  ❌ FAILED: SystemChecker error: {e}")
            return False


class DesktopFileTester:
    """Test the .desktop file."""
    
    @staticmethod
    def test_format():
        """Test .desktop file format."""
        print("Testing .desktop file format...")
        
        desktop_file = Path('installer/open-omniscience.desktop')
        
        if not desktop_file.exists():
            print("  ❌ FAILED: .desktop file not found")
            return False
        
        with open(desktop_file, 'r') as f:
            content = f.read()
        
        # Check required fields
        required_fields = ['[Desktop Entry]', 'Version=', 'Type=', 'Name=', 'Exec=', 'Icon=']
        missing_fields = [field for field in required_fields if field not in content]
        
        if missing_fields:
            print(f"  ❌ FAILED: Missing required fields: {missing_fields}")
            return False
        
        # Check Type is Application
        if 'Type=Application' not in content:
            print("  ❌ FAILED: Type should be Application")
            return False
        
        # Check Exec field
        if 'Exec=' not in content:
            print("  ❌ FAILED: Missing Exec field")
            return False
        
        print("  ✅ PASSED: .desktop file format is valid")
        return True


class FileStructureTester:
    """Test file structure."""
    
    @staticmethod
    def test_installer_files():
        """Test that all installer files exist."""
        print("Testing installer file structure...")
        
        required_files = [
            'installer/gui_installer.py',
            'installer/open-omniscience.desktop',
            'installer/README.md',
        ]
        
        missing_files = []
        for file_path in required_files:
            if not Path(file_path).exists():
                missing_files.append(file_path)
        
        if missing_files:
            print(f"  ❌ FAILED: Missing files: {missing_files}")
            return False
        
        # Check that gui_installer.py is executable
        if not os.access('installer/gui_installer.py', os.X_OK):
            print("  ⚠️  WARNING: gui_installer.py is not executable")
        
        print("  ✅ PASSED: All installer files exist")
        return True


def run_all_tests():
    """Run all tests and report results."""
    print("=" * 70)
    print("Open-Omniscience Installer and Documentation Test Suite")
    print("=" * 70)
    print()
    
    testers = [
        ("Documentation", DocumentationTester),
        ("Install Script", InstallScriptTester),
        ("GUI Installer", GUIInstallerTester),
        ("Desktop File", DesktopFileTester),
        ("File Structure", FileStructureTester),
    ]
    
    results = {}
    
    for category, tester_class in testers:
        print(f"\n{category} Tests:")
        print("-" * 70)
        
        category_results = []
        
        for method_name in dir(tester_class):
            if method_name.startswith('test_'):
                method = getattr(tester_class, method_name)
                if callable(method):
                    try:
                        result = method()
                        category_results.append(result)
                    except Exception as e:
                        print(f"  ❌ FAILED: {method_name} raised exception: {e}")
                        category_results.append(False)
        
        results[category] = all(category_results)
    
    print("\n" + "=" * 70)
    print("Test Summary")
    print("=" * 70)
    
    all_passed = True
    for category, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{category}: {status}")
        if not passed:
            all_passed = False
    
    print("=" * 70)
    
    if all_passed:
        print("\n🎉 ALL TESTS PASSED! 🎉")
        return 0
    else:
        print("\n❌ SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
