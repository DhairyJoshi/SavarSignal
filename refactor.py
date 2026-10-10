import os
import re

def organize_project():
    """Restructures the flat directory into a proper FastAPI app/core layout."""
    
    # Create new directories
    os.makedirs('app/core', exist_ok=True)
    open('app/__init__.py', 'w').close()
    open('app/core/__init__.py', 'w').close()

    core_modules = ['ingest', 'normalize', 'baseline', 'detect', 'causes', 'narrate', 'render', 'history']
    app_modules = ['config', 'datagen']
    files = core_modules + app_modules + ['app']

    for mod in files:
        filename = f'{mod}.py'
        if not os.path.exists(filename):
            continue
            
        with open(filename, 'r', encoding='utf-8') as f:
            content = f.read()

        # Update absolute imports
        for cm in core_modules:
            content = re.sub(rf'^from {cm} import', f'from app.core.{cm} import', content, flags=re.MULTILINE)
            content = re.sub(rf'^import {cm}\b', f'import app.core.{cm} as {cm}', content, flags=re.MULTILINE)

        for am in app_modules:
            content = re.sub(rf'^from {am} import', f'from app.{am} import', content, flags=re.MULTILINE)
            content = re.sub(rf'^import {am}\b', f'import app.{am} as {am}', content, flags=re.MULTILINE)

        # Update specific relative path definitions
        if mod == 'app':
            content = content.replace('os.path.dirname(__file__)', 'os.path.dirname(os.path.dirname(__file__))')
        elif mod == 'render' or mod == 'history':
            content = content.replace('os.path.dirname(__file__)', 'os.path.dirname(os.path.dirname(os.path.dirname(__file__)))')
        elif mod == 'config':
            content = content.replace('os.path.dirname(os.path.abspath(__file__))', 'os.path.dirname(os.path.dirname(os.path.abspath(__file__)))')

        # Determine new path
        if mod in core_modules:
            new_path = f'app/core/{mod}.py'
        elif mod == 'app':
            new_path = 'app/main.py'
        else:
            new_path = f'app/{mod}.py'

        # Write and cleanup
        with open(new_path, 'w', encoding='utf-8') as f:
            f.write(content)
        os.remove(filename)

    # Update Pytest imports in tests/ folder
    if os.path.exists('tests'):
        for test_file in os.listdir('tests'):
            if not test_file.endswith('.py'):
                continue
            filepath = os.path.join('tests', test_file)
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            for cm in core_modules:
                content = re.sub(rf'^from {cm} import', f'from app.core.{cm} import', content, flags=re.MULTILINE)
            for am in app_modules:
                content = re.sub(rf'^from {am} import', f'from app.{am} import', content, flags=re.MULTILINE)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
                
    print("✅ Project successfully reorganized into app/core/ structure!")
    print("You can now start the server with: uvicorn app.main:app --reload")

if __name__ == '__main__':
    organize_project()
