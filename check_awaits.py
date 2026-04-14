import ast
import os

for root, dirs, files in os.walk('app'):
    for file in files:
        if not file.endswith('.py'): continue
        path = os.path.join(root, file)
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        try:
            tree = ast.parse(content, filename=path)
        except SyntaxError:
            continue
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Await):
                val = node.value
                if isinstance(val, ast.Call) and isinstance(val.func, ast.Attribute):
                    if val.func.attr not in ('execute', 'get_auth_users', 'delete_auth_user', 'criar_pagamento_pix', 'processar_pagamento_asaas', 'criar_cartao', 'criar_cliente_asaas'):
                        # let's see if the code resembles supabase.table
                        source = ast.unparse(val)
                        if 'supabase' in source:
                            print(f"{path}:{node.lineno}: await {source}")
