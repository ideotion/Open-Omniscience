#!/usr/bin/env python3
"""
Test script to verify API endpoints functionality using FastAPI TestClient
"""
import sys
import os
import uuid

# Add the project root to Python path
sys.path.insert(0, '/workspace/ideotion__Open-Omniscience')

def test_api_endpoints():
    """Test all API endpoints using TestClient"""
    print("🧪 Testing API Endpoints with TestClient:")
    print("-" * 60)
    
    try:
        from src.api.main import app
        from fastapi.testclient import TestClient
        
        client = TestClient(app)
        
        tests = [
            # Health and basic endpoints
            ('/api/health', 'GET', 200, None),
            ('/', 'GET', 200, None),
            ('/api/sources', 'GET', 200, None),
            ('/api/articles', 'GET', 200, None),
            ('/api/articles/export', 'GET', 200, None),
            
            # LLM endpoints
            ('/api/llm/health', 'GET', 200, None),
            ('/api/llm/models', 'GET', 200, None),
            ('/api/llm/capabilities', 'GET', 200, None),
            
            # Keyword endpoints (using actual routes)
            ('/api/keywords/extract?text=test', 'GET', 200, None),
            
            # Link analysis endpoints (using actual routes)
            ('/api/link-analysis/health', 'GET', 200, None),  # link_analysis route
            
            # Source management endpoints
            ('/api/sources/', 'POST', 200, {'name': 'Test Source', 'domain': 'test-' + str(uuid.uuid4().hex[:8]) + '.com'}),
            
            # Article search with query
            ('/api/articles?q=test', 'GET', 200, None),
        ]
        
        results = []
        for url, method, expected_status, data in tests:
            try:
                if method == 'GET':
                    response = client.get(url)
                elif method == 'POST':
                    response = client.post(url, json=data)
                elif method == 'PUT':
                    response = client.put(url, json=data)
                elif method == 'DELETE':
                    response = client.delete(url)
                else:
                    results.append(False)
                    print(f"✗ {url} - Unsupported method: {method}")
                    continue
                
                if response.status_code == expected_status:
                    results.append(True)
                    print(f"✓ {method} {url} - {response.status_code}")
                else:
                    results.append(False)
                    print(f"✗ {method} {url} - Expected {expected_status}, got {response.status_code}")
                    if response.text:
                        print(f"  Response: {response.text[:200]}")
            except Exception as e:
                results.append(False)
                print(f"✗ {method} {url} - Exception: {str(e)}")
        
        # Summary
        passed = sum(results)
        total = len(results)
        print("-" * 60)
        print(f"Results: {passed}/{total} endpoints passed")
        
        return passed == total
        
    except Exception as e:
        print(f"❌ Failed to initialize TestClient: {e}")
        return False

def main():
    """Run all tests"""
    print("=" * 60)
    print("OPEN OMNISCIENCE - API ENDPOINT TESTS (TestClient)")
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