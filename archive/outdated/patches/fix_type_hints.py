#!/usr/bin/env python3
"""
Script to fix type hint issues in llm.py
Replaces placeholder type hints with proper types
"""

from pathlib import Path

def fix_type_hints():
    """Fix type hint issues in llm.py"""
    
    file_path = Path("src/api/routes/llm.py")
    
    if not file_path.exists():
        print(f"❌ File not found: {file_path}")
        return False
    
    # Read the file
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Fix all placeholder type hints - the placeholder appears to be asterisks with brackets
    # Replace "max_tokens: ********] = Field(" with "max_tokens: Optional[int] = Field("
    content = content.replace('max_tokens: ********] = Field(', 'max_tokens: Optional[int] = Field(')
    
    # Write the fixed content
    with open(file_path, 'w') as f:
        f.write(content)
    
    print(f"✅ Fixed type hint issues in {file_path}")
    return True

if __name__ == "__main__":
    success = fix_type_hints()
    if success:
        print("✅ Type hint fix applied successfully!")
    else:
        print("❌ Failed to apply type hint fix")
        exit(1)
