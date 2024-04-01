import re
import os

# Путь к вашему проекту
project_path = '/home/ubuntu/bladeVPN_bot/'

# Регулярное выражение для поиска строк
regex = re.compile(r'\"(.+?)\"|\'(.+?)\'')

strings = []

for root, dirs, files in os.walk(project_path):
    if 'venv' in dirs:
        dirs.remove('venv')  # don't visit this directory
    if '.venv' in dirs:
        dirs.remove('.venv')
    if '__pycache__' in dirs:
        dirs.remove('__pycache__')
    for file in files:
        if file.endswith('.py'):
            with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                content = f.read()
                matches = regex.findall(content)
                for match in matches:
                    # Добавление найденных строк в список
                    strings.append(match[0] if match[0] else match[1])

# Экспорт найденных строк в файл
with open('strings.txt', 'w', encoding='utf-8') as f:
    for string in strings:
        f.write(string + '\n')