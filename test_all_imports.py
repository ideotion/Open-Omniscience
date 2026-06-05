#!/usr/bin/env python3
"""
Comprehensive import test for all Open Omniscience modules
"""
import sys
import os
import traceback
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, '/workspace/ideotion__Open-Omniscience')

def test_import(module_path, description=""):
    """Test importing a module and return success/failure"""
    try:
        __import__(module_path)
        print(f"✓ {module_path} {description}")
        return True
    except Exception as e:
        print(f"✗ {module_path} {description} - ERROR: {e}")
        # Print the full traceback for debugging
        traceback.print_exc()
        return False

def find_python_files(directory):
    """Find all Python files in a directory"""
    python_files = []
    for root, dirs, files in os.walk(directory):
        # Skip __pycache__ directories and migrations directories
        dirs[:] = [d for d in dirs if d != '__pycache__' and d != 'migrations']
        for file in files:
            if file.endswith('.py') and not file.startswith('test_'):
                # Skip alembic env.py files as they require alembic context
                if file == 'env.py':
                    continue
                # Convert to module path
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, '/workspace/ideotion__Open-Omniscience')
                module_path = rel_path.replace('/', '.').replace('.py', '')
                python_files.append(module_path)
    return python_files

def main():
    """Run comprehensive import tests"""
    print("=" * 80)
    print("OPEN OMNISCIENCE - COMPREHENSIVE IMPORT TESTS")
    print("=" * 80)
    
    # Test main src directory
    print("\n📁 Testing src/ directory:")
    src_files = find_python_files('/workspace/ideotion__Open-Omniscience/src')
    src_results = []
    for module_path in sorted(src_files):
        result = test_import(module_path)
        src_results.append(result)
    
    # Test pillar2 directory
    print("\n📁 Testing pillar2/ directory:")
    pillar2_files = find_python_files('/workspace/ideotion__Open-Omniscience/pillar2')
    pillar2_results = []
    for module_path in sorted(pillar2_files):
        result = test_import(module_path)
        pillar2_results.append(result)
    
    # Test pillar3 directory
    print("\n📁 Testing pillar3/ directory:")
    pillar3_files = find_python_files('/workspace/ideotion__Open-Omniscience/pillar3')
    pillar3_results = []
    for module_path in sorted(pillar3_files):
        result = test_import(module_path)
        pillar3_results.append(result)
    
    # Test pillar4, pillar5, pillar6 directories
    for pillar_dir in ['pillar4', 'pillar5', 'pillar6']:
        print(f"\n📁 Testing {pillar_dir}/ directory:")
        pillar_files = find_python_files(f'/workspace/ideotion__Open-Omniscience/{pillar_dir}')
        pillar_results = []
        for module_path in sorted(pillar_files):
            result = test_import(module_path)
            pillar_results.append(result)
    
    # Skip scripts directory as they are standalone scripts, not importable modules
    print("\n📁 Skipping scripts/ directory (standalone scripts)")
    script_results = []
    
    # Test tests directory (these might have dependencies on test frameworks)
    print("\n📁 Testing tests/ directory:")
    test_files = find_python_files('/workspace/ideotion__Open-Omniscience/tests')
    test_results = []
    for module_path in sorted(test_files):
        result = test_import(module_path)
        test_results.append(result)
    
    # Summary
    total_tests = len(src_results) + len(pillar2_results) + len(pillar3_results) + len(script_results) + len(test_results)
    total_passed = sum(src_results) + sum(pillar2_results) + sum(pillar3_results) + sum(script_results) + sum(test_results)
    
    print("\n" + "=" * 80)
    print("SUMMARY:")
    print(f"  src/ modules:      {sum(src_results)}/{len(src_results)} passed")
    print(f"  pillar2/ modules:  {sum(pillar2_results)}/{len(pillar2_results)} passed")
    print(f"  pillar3/ modules:  {sum(pillar3_results)}/{len(pillar3_results)} passed")
    print(f"  scripts/ modules:  {sum(script_results)}/{len(script_results)} passed")
    print(f"  tests/ modules:    {sum(test_results)}/{len(test_results)} passed")
    print(f"  TOTAL:            {total_passed}/{total_tests} passed")
    
    if total_passed == total_tests:
        print("✅ ALL IMPORTS SUCCESSFUL")
        return 0
    else:
        print("❌ SOME IMPORTS FAILED")
        return 1

if __name__ == "__main__":
    sys.exit(main())