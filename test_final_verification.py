#!/usr/bin/env python3
"""
Final comprehensive verification test for Open Omniscience
Runs all tests and provides a complete status report
"""
import sys
import os
import subprocess
import time

# Add the project root to Python path
sys.path.insert(0, '/workspace/ideotion__Open-Omniscience')

def run_test(test_name, test_script, timeout=120):
    """Run a test script and return results"""
    print(f"\n{'='*60}")
    print(f"🧪 Running: {test_name}")
    print('='*60)
    
    try:
        result = subprocess.run(
            [sys.executable, test_script],
            cwd='/workspace/ideotion__Open-Omniscience',
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        # Print the output
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
        
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"❌ {test_name} TIMED OUT after {timeout} seconds")
        return False
    except Exception as e:
        print(f"❌ {test_name} FAILED with exception: {e}")
        return False

def main():
    """Run all verification tests"""
    print("=" * 80)
    print("OPEN OMNISCIENCE - FINAL COMPREHENSIVE VERIFICATION")
    print("=" * 80)
    print(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Python: {sys.version}")
    print(f"Working Directory: {os.getcwd()}")
    
    tests = [
        ("Import Tests", "test_all_imports.py"),
        ("API Endpoint Tests", "test_api_with_testclient.py"),
        ("Edge Case Tests", "test_edge_cases.py"),
    ]
    
    results = []
    for test_name, test_script in tests:
        if os.path.exists(test_script):
            success = run_test(test_name, test_script)
            results.append((test_name, success))
        else:
            print(f"⚠️  Test script not found: {test_script}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 80)
    print("FINAL VERIFICATION SUMMARY")
    print("=" * 80)
    
    for test_name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} - {test_name}")
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    print(f"\nOverall: {passed}/{total} test suites passed")
    
    if passed == total:
        print("\n🎉 ALL VERIFICATION TESTS PASSED!")
        print("The Open Omniscience application is now fully functional.")
        return 0
    else:
        print("\n⚠️  SOME VERIFICATION TESTS FAILED")
        print("Please review the output above for details.")
        return 1

if __name__ == "__main__":
    sys.exit(main())