#!/usr/bin/env python3
"""
Script to fix pickle security issue in source_monitor.py
Replaces pickle with JSON for caching
"""

import re
from pathlib import Path

def fix_pickle_security():
    """Fix pickle security issue in source_monitor.py"""
    
    file_path = Path("src/scraper/source_monitor.py")
    
    if not file_path.exists():
        print(f"❌ File not found: {file_path}")
        return False
    
    # Read the file
    with open(file_path, 'r') as f:
        content = f.read()
    
    original_content = content
    
    # Fix 1: Replace pickle import with json
    content = content.replace(
        "import pickle",
        "import json"
    )
    
    # Fix 2: Replace pickle.load with json.load and change file extension
    content = re.sub(
        r'cache_file = self\.cache_dir / "response_cache\.pkl"',
        'cache_file = self.cache_dir / "response_cache.json"',
        content
    )
    
    content = re.sub(
        r'with open\(cache_file, "rb"\) as f:\s+self\._response_cache = pickle\.load\(f\)',
        '''with open(cache_file, "r") as f:
                self._response_cache = json.load(f)''',
        content
    )
    
    # Fix 3: Replace pickle.dump with json.dump
    content = re.sub(
        r'with open\(cache_file, "wb"\) as f:\s+pickle\.dump\(self\._response_cache, f\)',
        '''with open(cache_file, "w") as f:
                json.dump(self._response_cache, f)''',
        content
    )
    
    # Fix 4: Add error handling for JSON decode errors
    content = re.sub(
        r'except Exception as e:',
        'except (json.JSONDecodeError, Exception) as e:',
        content,
        count=1  # Only replace the first occurrence (in _load_cache)
    )
    
    # Write the fixed content
    with open(file_path, 'w') as f:
        f.write(content)
    
    print(f"✅ Fixed pickle security issue in {file_path}")
    return True

if __name__ == "__main__":
    success = fix_pickle_security()
    if success:
        print("✅ Pickle security fix applied successfully!")
    else:
        print("❌ Failed to apply pickle security fix")
        exit(1)
