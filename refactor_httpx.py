import os
import re

filepath = r'app\api\auth.py'

with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace 
# auth_response = httpx.post(...)
# with
# async with httpx.AsyncClient() as _client:
#     auth_response = await _client.post(...)

content = re.sub(
    r'(?P<indent>\s*)auth_response = httpx\.post\((?P<args>.*?)\)',
    r'\g<indent>async with httpx.AsyncClient() as _client:\n\g<indent>    auth_response = await _client.post(\g<args>)',
    content
)

content = re.sub(
    r'(?P<indent>\s*)auth_response = httpx\.put\((?P<args>.*?)\)',
    r'\g<indent>async with httpx.AsyncClient() as _client:\n\g<indent>    auth_response = await _client.put(\g<args>)',
    content
)

content = re.sub(
    r'(?P<indent>\s*)httpx\.post\((?P<args>.*?)\)',
    r'\g<indent>async with httpx.AsyncClient() as _client:\n\g<indent>    await _client.post(\g<args>)',
    content
)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

print(f"Refactored httpx in: {filepath}")
