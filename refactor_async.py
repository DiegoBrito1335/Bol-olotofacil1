import os
import re

def process_file(filepath):
    if 'supabase.py' in filepath:
        return

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    original_content = content

    # Rule 1: add await before supabase.table or supabase.rpc
    content = re.sub(r'(?<!await\s)\b(supabase\.table|supabase\.rpc|supabase_admin\.table|supabase_admin\.rpc|supabase\.get_auth_users|supabase\.delete_auth_user)', r'await \1', content)

    # Rule 2: add await before query.execute()
    content = re.sub(r'(?<!await\s)\b(query\.execute\(\))', r'await \1', content)

    if content != original_content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Refactored: {filepath}")

for root, _, files in os.walk('app'):
    for file in files:
        if file.endswith('.py'):
            process_file(os.path.join(root, file))
