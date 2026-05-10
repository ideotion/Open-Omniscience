#!/usr/bin/env python3
"""
Basic test to verify the Open-Omniscience structure
"""
import sys
import os

def test_imports():
    """Test that all basic imports work"""
    print("Testing imports...")
    
    try:
        backend_src = os.path.join(os.path.dirname(__file__), 'backend', 'src')
        sys.path.insert(0, backend_src)
        
        from database.session import engine, Base, get_db, init_db
        print("✓ Database session imports work")
        
        from database.models import Article, Keyword, Source
        print("✓ Database models import work")
        
        print("\n✅ Basic imports successful!")
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def test_database():
    """Test database initialization"""
    print("\nTesting database...")
    
    try:
        backend_src = os.path.join(os.path.dirname(__file__), 'backend', 'src')
        sys.path.insert(0, backend_src)
        
        from database.session import init_db, engine
        from database.models import Base
        
        init_db()
        print("✓ Database initialized")
        
        with engine.connect() as conn:
            print("✓ Database connection works")
        
        print("\n✅ Database tests successful!")
        return True
        
    except Exception as e:
        print(f"❌ Database error: {e}")
        return False

def test_fastapi():
    """Test FastAPI app"""
    print("\nTesting FastAPI...")
    
    try:
        backend_src = os.path.join(os.path.dirname(__file__), 'backend', 'src')
        sys.path.insert(0, backend_src)
        
        # Import database first
        from database.session import init_db, engine
        from database.models import Base
        
        # Initialize database
        init_db()
        
        # Now import main as a module
        import main
        app = main.app
        
        # Test that app is a FastAPI instance
        assert hasattr(app, 'get'), "App should have get method"
        assert hasattr(app, 'post'), "App should have post method"
        print("✓ FastAPI app is valid")
        
        # Test health endpoint
        from fastapi.testclient import TestClient
        client = TestClient(app)
        
        response = client.get("/health")
        assert response.status_code == 200, "Health endpoint should return 200"
        assert response.json()["status"] == "healthy", "Health endpoint should return healthy status"
        print("✓ Health endpoint works")
        
        response2 = client.get("/")
        assert response2.status_code == 200, "Root endpoint should return 200"
        print("✓ Root endpoint works")
        
        print("\n✅ FastAPI tests successful!")
        return True
        
    except Exception as e:
        print(f"❌ FastAPI error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Running Open-Omniscience basic tests...\n")
    
    results = []
    results.append(test_imports())
    results.append(test_database())
    results.append(test_fastapi())
    
    if all(results):
        print("\n🎉 All tests passed!")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed!")
        sys.exit(1)
