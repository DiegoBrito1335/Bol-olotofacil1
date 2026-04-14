import ast
import os

def check():
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
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr == 'execute':
                        # Check if this Call is inside an Await node
                        # We need to trace parents. Let's do it by scanning the source lines roughly
                        # Or better, let's keep a parent map
                        pass

if __name__ == "__main__":
    check()
