#!/usr/bin/env python3
"""
Test script to verify API startup and basic functionality
"""
import sys
import os
import time
import subprocess
import requests
import signal

# Add the project root to Python path
sys.path.insert(0, '/workspace/ideotion__Open-Omniscience')

def test_api_import():
    """Test that the API can be imported"""
    print("Testing API import...")
    try:
        from src.api.main import app
        print("✓ API imported successfully")
        return True
    except Exception as e:
        print(f"✗ API import failed: {e}")
        return False

def test_database_connection():
    """Test database connection"""
    print("Testing database connection...")
    try:
        from src.database.models import get_session, Article, Source
        session = get_session()
        
        # Test query
        articles = session.query(Article).limit(5).all()
        sources = session.query(Source).limit(5).all()
        
        session.close()
        print(f"✓ Database connection successful: {len(articles)} articles, {len(sources)} sources")
        return True
    except Exception as e:
        print(f"✗ Database connection failed: {e}")
        return False

def test_routes_import():
    """Test that all routes can be imported"""
    print("Testing route imports...")
    try:
        # Test main API routes
        from src.api.main import app
        from src.api.source_management import router as source_router
        from src.api.keyword_management import router as keyword_router
        from src.api.keyword_analysis import router as keyword_analysis_router
        from src.api.link_analysis import router as link_analysis_router
        from src.api.routes.llm import router as llm_router
        
        print("✓ All route imports successful")
        return True
    except Exception as e:
        print(f"✗ Route import failed: {e}")
        return False

def test_services_import():
    """Test that all services can be imported"""
    print("Testing services import...")
    try:
        # Test various services
        from src.services.article_intelligence import article_intelligence_analyzer
        from src.services.link_analyzer import LinkAnalyzerService
        from src.services.keyword_extractor import KeywordExtractor
        
        print("✓ All services imported successfully")
        return True
    except Exception as e:
        print(f"✗ Services import failed: {e}")
        return False

def test_utils_import():
    """Test that all utilities can be imported"""
    print("Testing utilities import...")
    try:
        from src.utils.security import sanitize_html, validate_and_sanitize_search_query
        from src.utils.logging_config import setup_logging
        from src.utils.compression import database_compressor
        
        print("✓ All utilities imported successfully")
        return True
    except Exception as e:
        print(f"✗ Utilities import failed: {e}")
        return False

def main():
    """Run all tests"""
    print("=" * 60)
    print("OPEN OMNISCIENCE - API STARTUP TESTS")
    print("=" * 60)
    
    tests = [
        test_api_import,
        test_database_connection,
        test_routes_import,
        test_services_import,
        test_utils_import,
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"✗ Test {test.__name__} crashed: {e}")
            results.append(False)
        print()
    
    passed = sum(results)
    total = len(results)
    
    print("=" * 60)
    print(f"RESULTS: {passed}/{total} tests passed")
    
    if passed == total:
        print("✓ ALL TESTS PASSED")
        return 0
    else:
        print("✗ SOME TESTS FAILED")
        return 1

if __name__ == "__main__":
    sys.exit(main())