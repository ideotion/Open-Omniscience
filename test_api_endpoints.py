#!/usr/bin/env python3
"""
Test script to verify API endpoints functionality
"""
import sys
import os
import subprocess
import time
import requests
import signal
import threading
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, '/workspace/ideotion__Open-Omniscience')

def start_server(port=8002):
    """Start the Uvicorn server in a separate thread"""
    cmd = [
        sys.executable, '-m', 'uvicorn',
        'src.api.main:app',
        '--host', '0.0.0.0',
        '--port', str(port),
        '--log-level', 'warning'
    ]
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd='/workspace/ideotion__Open-Omniscience'
    )
    
    # Wait for server to start
    time.sleep(3)
    
    return process

def test_endpoint(url, expected_status=200, data=None, method='GET', timeout=10):
    """Test a single API endpoint"""
    try:
        if method == 'GET':
            response = requests.get(url, timeout=timeout)
        elif method == 'POST':
            response = requests.post(url, json=data, timeout=timeout)
        elif method == 'PUT':
            response = requests.put(url, json=data, timeout=timeout)
        elif method == 'DELETE':
            response = requests.delete(url, timeout=timeout)
        else:
            return False, f"Unsupported method: {method}"
        
        if response.status_code == expected_status:
            return True, f"✓ {url} - {response.status_code}"
        else:
            return False, f"✗ {url} - Expected {expected_status}, got {response.status_code}: {response.text[:200]}"
    except Exception as e:
        return False, f"✗ {url} - Exception: {str(e)}"

def test_api_endpoints():
    """Test all API endpoints"""
    port = 8002
    base_url = f"http://localhost:{port}"
    
    # Start the server
    print(f"Starting server on port {port}...")
    server_process = start_server(port)
    
    try:
        # Wait a bit more for the server to be ready
        time.sleep(2)
        
        # Test basic health endpoint
        print("\n🧪 Testing API Endpoints:")
        print("-" * 50)
        
        tests = [
            # Health and basic endpoints
            (f"{base_url}/api/health", 'GET', 200),
            (f"{base_url}/", 'GET', 200),
            (f"{base_url}/api/sources", 'GET', 200),
            (f"{base_url}/api/articles", 'GET', 200),
            (f"{base_url}/api/articles/export", 'GET', 200),
            
            # LLM endpoints (these might fail if Ollama is not running, but should not crash)
            (f"{base_url}/api/llm/health", 'GET', 200),
            (f"{base_url}/api/llm/models", 'GET', 200),
            (f"{base_url}/api/llm/capabilities", 'GET', 200),
            
            # Keyword endpoints
            (f"{base_url}/api/keywords", 'GET', 200),
            (f"{base_url}/api/keywords/analysis", 'GET', 200),
            
            # Link analysis endpoints
            (f"{base_url}/api/links", 'GET', 200),
            (f"{base_url}/api/links/analysis", 'GET', 200),
        ]
        
        results = []
        for url, method, expected_status in tests:
            success, message = test_endpoint(url, expected_status, method=method)
            results.append(success)
            print(message)
        
        # Summary
        passed = sum(results)
        total = len(results)
        print("-" * 50)
        print(f"Results: {passed}/{total} endpoints passed")
        
        return passed == total
        
    finally:
        # Clean up
        print(f"\nStopping server...")
        server_process.terminate()
        server_process.wait(timeout=5)

def main():
    """Run all tests"""
    print("=" * 60)
    print("OPEN OMNISCIENCE - API ENDPOINT TESTS")
    print("=" * 60)
    
    try:
        success = test_api_endpoints()
        if success:
            print("✅ ALL API ENDPOINT TESTS PASSED")
            return 0
        else:
            print("❌ SOME API ENDPOINT TESTS FAILED")
            return 1
    except Exception as e:
        print(f"❌ API ENDPOINT TESTS CRASHED: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())