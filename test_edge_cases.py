#!/usr/bin/env python3
"""
Comprehensive edge case and failure mode testing for Open Omniscience
"""
import sys
import os

# Add the project root to Python path
sys.path.insert(0, '/workspace/ideotion__Open-Omniscience')

def test_edge_cases():
    """Test edge cases and failure modes"""
    from src.api.main import app
    from fastapi.testclient import TestClient
    
    client = TestClient(app)
    
    print("🧪 Testing Edge Cases and Failure Modes:")
    print("=" * 60)
    
    test_results = []
    
    # ========================================================================
    # 1. HEALTH ENDPOINT EDGE CASES
    # ========================================================================
    print("\n📋 1. Health Endpoint Edge Cases:")
    print("-" * 40)
    
    # Test health endpoint with various methods
    tests = [
        ('GET /api/health', lambda: client.get('/api/health'), 200),
        ('POST /api/health', lambda: client.post('/api/health'), 405),  # Method not allowed
        ('PUT /api/health', lambda: client.put('/api/health'), 405),
        ('DELETE /api/health', lambda: client.delete('/api/health'), 405),
    ]
    
    for test_name, test_func, expected_status in tests:
        try:
            response = test_func()
            success = response.status_code == expected_status
            status = "✓" if success else "✗"
            print(f"{status} {test_name} - Expected {expected_status}, got {response.status_code}")
            test_results.append(success)
        except Exception as e:
            print(f"✗ {test_name} - Exception: {str(e)}")
            test_results.append(False)
    
    # ========================================================================
    # 2. ARTICLE SEARCH EDGE CASES
    # ========================================================================
    print("\n📋 2. Article Search Edge Cases:")
    print("-" * 40)
    
    article_tests = [
        # Empty and null queries
        ('Empty query', lambda: client.get('/api/articles?q='), 200),
        ('No query param', lambda: client.get('/api/articles'), 200),
        ('Null query', lambda: client.get('/api/articles?q=None'), 200),
        
        # Invalid parameters
        ('Invalid limit (0)', lambda: client.get('/api/articles?limit=0'), 400),
        ('Invalid limit (negative)', lambda: client.get('/api/articles?limit=-1'), 400),
        ('Invalid limit (too high)', lambda: client.get('/api/articles?limit=1001'), 400),
        ('Invalid offset (negative)', lambda: client.get('/api/articles?offset=-1'), 400),
        
        # Invalid date formats
        ('Invalid start_date', lambda: client.get('/api/articles?start_date=invalid'), 400),
        ('Invalid end_date', lambda: client.get('/api/articles?end_date=invalid'), 400),
        
        # Special characters in query
        ('Special chars in query', lambda: client.get('/api/articles?q=<script>alert(1)</script>'), 200),
        ('SQL injection attempt', lambda: client.get('/api/articles?q=\' OR 1=1 --'), 200),
        ('Unicode in query', lambda: client.get('/api/articles?q=测试'), 200),
        ('Very long query', lambda: client.get('/api/articles?q=' + 'a' * 1000), 200),
        
        # Non-existent source
        ('Non-existent source', lambda: client.get('/api/articles?source=NonExistentSource'), 404),
        
        # Valid but edge cases
        ('Limit at boundary (1)', lambda: client.get('/api/articles?limit=1'), 200),
        ('Limit at boundary (1000)', lambda: client.get('/api/articles?limit=1000'), 200),
        ('Offset at boundary (0)', lambda: client.get('/api/articles?offset=0'), 200),
    ]
    
    for test_name, test_func, expected_status in article_tests:
        try:
            response = test_func()
            success = response.status_code == expected_status
            status = "✓" if success else "✗"
            print(f"{status} {test_name} - Expected {expected_status}, got {response.status_code}")
            test_results.append(success)
        except Exception as e:
            print(f"✗ {test_name} - Exception: {str(e)}")
            test_results.append(False)
    
    # ========================================================================
    # 3. SOURCE MANAGEMENT EDGE CASES
    # ========================================================================
    print("\n📋 3. Source Management Edge Cases:")
    print("-" * 40)
    
    # Use a counter to generate unique domains for each test
    import uuid
    test_counter = 0
    
    def get_unique_domain():
        nonlocal test_counter
        test_counter += 1
        return f"test-domain-{test_counter}-{uuid.uuid4().hex[:8]}.com"
    
    # Create a source first for duplicate test
    duplicate_domain = "duplicate-test-" + uuid.uuid4().hex[:8] + ".com"
    client.post('/api/sources/', json={'name': 'DuplicateTest', 'domain': duplicate_domain})
    
    source_tests = [
        # GET all sources
        ('GET all sources', lambda: client.get('/api/sources'), 200),
        
        # POST with invalid data
        ('POST with missing name', lambda: client.post('/api/sources/', json={'domain': get_unique_domain()}), 422),
        ('POST with missing domain', lambda: client.post('/api/sources/', json={'name': 'Test'}), 422),
        ('POST with duplicate domain', lambda: client.post('/api/sources/', json={'name': 'Test', 'domain': duplicate_domain}), 400),
        ('POST with empty name', lambda: client.post('/api/sources/', json={'name': '', 'domain': get_unique_domain()}), 422),
        ('POST with empty domain', lambda: client.post('/api/sources/', json={'name': 'Test2', 'domain': ''}), 422),
        
        # POST with special characters
        ('POST with special chars in name', lambda: client.post('/api/sources/', json={'name': '<script>Test</script>', 'domain': get_unique_domain()}), 200),
        ('POST with unicode in name', lambda: client.post('/api/sources/', json={'name': '测试源', 'domain': get_unique_domain()}), 200),
        
        # POST with very long values (within database limits)
        ('POST with very long name', lambda: client.post('/api/sources/', json={'name': 'A' * 200, 'domain': get_unique_domain()}), 200),
        ('POST with very long domain', lambda: client.post('/api/sources/', json={'name': 'Test6', 'domain': 'a' * 200 + '-' + uuid.uuid4().hex[:8] + '.com'}), 200),
    ]
    
    for test_name, test_func, expected_status in source_tests:
        try:
            response = test_func()
            success = response.status_code == expected_status
            status = "✓" if success else "✗"
            print(f"{status} {test_name} - Expected {expected_status}, got {response.status_code}")
            test_results.append(success)
        except Exception as e:
            print(f"✗ {test_name} - Exception: {str(e)}")
            test_results.append(False)
    
    # ========================================================================
    # 4. EXPORT ENDPOINT EDGE CASES
    # ========================================================================
    print("\n📋 4. Export Endpoint Edge Cases:")
    print("-" * 40)
    
    export_tests = [
        # Valid formats
        ('CSV export', lambda: client.get('/api/articles/export?format=csv'), 200),
        ('JSON export', lambda: client.get('/api/articles/export?format=json'), 200),
        
        # Invalid format
        ('Invalid format', lambda: client.get('/api/articles/export?format=xml'), 400),
        ('Empty format', lambda: client.get('/api/articles/export?format='), 400),
        
        # With query parameters
        ('CSV with query', lambda: client.get('/api/articles/export?format=csv&q=test'), 200),
        ('JSON with query', lambda: client.get('/api/articles/export?format=json&q=test'), 200),
    ]
    
    for test_name, test_func, expected_status in export_tests:
        try:
            response = test_func()
            success = response.status_code == expected_status
            status = "✓" if success else "✗"
            print(f"{status} {test_name} - Expected {expected_status}, got {response.status_code}")
            test_results.append(success)
        except Exception as e:
            print(f"✗ {test_name} - Exception: {str(e)}")
            test_results.append(False)
    
    # ========================================================================
    # 5. LLM ENDPOINT EDGE CASES
    # ========================================================================
    print("\n📋 5. LLM Endpoint Edge Cases:")
    print("-" * 40)
    
    llm_tests = [
        # Health and info endpoints
        ('LLM health', lambda: client.get('/api/llm/health'), 200),
        ('LLM models', lambda: client.get('/api/llm/models'), 200),
        ('LLM capabilities', lambda: client.get('/api/llm/capabilities'), 200),
        
        # Generation endpoint (POST only)
        ('LLM generate GET', lambda: client.get('/api/llm/generate'), 405),  # Should be POST
        ('LLM generate POST empty', lambda: client.post('/api/llm/generate', json={}), 422),  # Missing required fields
        ('LLM generate POST missing prompt', lambda: client.post('/api/llm/generate', json={'temperature': 0.7}), 422),
        
        # Chat endpoint
        ('LLM chat GET', lambda: client.get('/api/llm/chat'), 405),  # Should be POST
        ('LLM chat POST empty', lambda: client.post('/api/llm/chat', json={}), 422),
        ('LLM chat POST missing messages', lambda: client.post('/api/llm/chat', json={'temperature': 0.7}), 422),
    ]
    
    for test_name, test_func, expected_status in llm_tests:
        try:
            response = test_func()
            success = response.status_code == expected_status
            status = "✓" if success else "✗"
            print(f"{status} {test_name} - Expected {expected_status}, got {response.status_code}")
            test_results.append(success)
        except Exception as e:
            print(f"✗ {test_name} - Exception: {str(e)}")
            test_results.append(False)
    
    # ========================================================================
    # 6. KEYWORD ENDPOINT EDGE CASES
    # ========================================================================
    print("\n📋 6. Keyword Endpoint Edge Cases:")
    print("-" * 40)
    
    keyword_tests = [
        # Extract endpoint
        ('Keyword extract empty text', lambda: client.get('/api/keywords/extract?text='), 200),
        ('Keyword extract no text param', lambda: client.get('/api/keywords/extract'), 422),
        ('Keyword extract very long text', lambda: client.get('/api/keywords/extract?text=' + 'word ' * 1000), 200),
        ('Keyword extract special chars', lambda: client.get('/api/keywords/extract?text=<script>test</script>'), 200),
        ('Keyword extract unicode', lambda: client.get('/api/keywords/extract?text=测试关键词'), 200),
    ]
    
    for test_name, test_func, expected_status in keyword_tests:
        try:
            response = test_func()
            success = response.status_code == expected_status
            status = "✓" if success else "✗"
            print(f"{status} {test_name} - Expected {expected_status}, got {response.status_code}")
            test_results.append(success)
        except Exception as e:
            print(f"✗ {test_name} - Exception: {str(e)}")
            test_results.append(False)
    
    # ========================================================================
    # 7. LINK ANALYSIS EDGE CASES
    # ========================================================================
    print("\n📋 7. Link Analysis Endpoint Edge Cases:")
    print("-" * 40)
    
    link_tests = [
        ('Link analysis health', lambda: client.get('/api/link-analysis/health'), 200),
        ('Link analysis extract empty', lambda: client.post('/api/link-analysis/extract-links', json={}), 422),
    ]
    
    for test_name, test_func, expected_status in link_tests:
        try:
            response = test_func()
            success = response.status_code == expected_status
            status = "✓" if success else "✗"
            print(f"{status} {test_name} - Expected {expected_status}, got {response.status_code}")
            test_results.append(success)
        except Exception as e:
            print(f"✗ {test_name} - Exception: {str(e)}")
            test_results.append(False)
    
    # ========================================================================
    # SUMMARY
    # ========================================================================
    print("\n" + "=" * 60)
    passed = sum(test_results)
    total = len(test_results)
    print(f"EDGE CASE TEST RESULTS: {passed}/{total} tests passed")
    
    if passed == total:
        print("✅ ALL EDGE CASE TESTS PASSED")
        return True
    else:
        print("❌ SOME EDGE CASE TESTS FAILED")
        return False

def main():
    """Run all edge case tests"""
    print("=" * 60)
    print("OPEN OMNISCIENCE - EDGE CASE AND FAILURE MODE TESTS")
    print("=" * 60)
    print()
    
    try:
        success = test_edge_cases()
        return 0 if success else 1
    except Exception as e:
        print(f"❌ EDGE CASE TESTS CRASHED: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())