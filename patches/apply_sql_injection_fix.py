#!/usr/bin/env python3
"""
Script to apply SQL injection fix to main.py
"""

from pathlib import Path

def apply_sql_injection_fix():
    """Apply SQL injection fix to main.py"""
    
    file_path = Path("src/api/main.py")
    
    if not file_path.exists():
        print(f"❌ File not found: {file_path}")
        return False
    
    # Read the file
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Fix 1: Update imports in build_sqlalchemy_filter
    content = content.replace(
        "from sqlalchemy import or_, and_, not_",
        "from sqlalchemy import or_, and_, not_, bindparam",
        1  # Only replace the first occurrence (in build_sqlalchemy_filter)
    )
    
    # Fix 2: Replace the vulnerable ilike with bindparam (exact match)
    content = content.replace(
        "filters.append(Article.content.ilike(f'%{term[\"value\"]}%'))",
        "# Use bindparam for safe parameter binding to prevent SQL injection\n            param = bindparam('search_term', term[\"value\"])\n            filters.append(Article.content.ilike('%' + param + '%'))"
    )
    
    # Fix 3: Replace the list comprehension with safe version
    content = content.replace(
        "word_conditions = [Article.content.ilike(f'%{word}%') for word in words]",
        "# Split into words for OR logic\n            word_conditions = []\n            for word in words:\n                param = bindparam('search_word', word)\n                word_conditions.append(Article.content.ilike('%' + param + '%'))"
    )
    
    # Fix 4: Fix tag filtering (first occurrence)
    content = content.replace(
        "tag_conditions = [Source.tags.ilike(f'%{tag}%') for tag in tag_list]",
        "from sqlalchemy import bindparam\n            tag_conditions = []\n            for tag in tag_list:\n                param = bindparam('tag_param', tag)\n                tag_conditions.append(Source.tags.ilike('%' + param + '%'))",
        1  # Only replace the first occurrence
    )
    
    # Fix 5: Fix tag filtering (second occurrence in export function)
    content = content.replace(
        "tag_conditions = [Source.tags.ilike(f'%{tag}%') for tag in tag_list]",
        "from sqlalchemy import bindparam\n            tag_conditions = []\n            for tag in tag_list:\n                param = bindparam('tag_param', tag)\n                tag_conditions.append(Source.tags.ilike('%' + param + '%'))",
        1  # Only replace the second occurrence
    )
    
    # Write the fixed content
    with open(file_path, 'w') as f:
        f.write(content)
    
    print(f"✅ Applied SQL injection fix to {file_path}")
    return True

if __name__ == "__main__":
    success = apply_sql_injection_fix()
    if success:
        print("✅ SQL injection fix applied successfully!")
    else:
        print("❌ Failed to apply SQL injection fix")
        exit(1)
