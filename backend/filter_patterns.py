# Common ignore patterns for file filtering
IGNORE_PATH_PATTERNS = {
    'node_modules', '.git', '__pycache__', '.pytest_cache',
    'venv', 'env', '.env', '.venv', '.idea', '.vscode'
}

IGNORE_FILE_PATTERNS = {
    'package-lock.json', 'yarn.lock', '.gitignore', '.DS_Store', 'pnpm-lock.yaml'
}

IGNORE_EXTENSIONS = {
    '.pyc', '.pyo', '.pyd', '.so', '.dll', '.dylib',
    '.log', '.tmp', '.temp', '.swp', '.svg', '.png', '.gif'
}

def get_default_exclude_patterns():
    """Returns a comma-separated string of default exclude patterns."""
    patterns = []
    
    # Add path patterns
    patterns.extend(IGNORE_PATH_PATTERNS)
    
    # Add file patterns
    patterns.extend(IGNORE_FILE_PATTERNS)
    
    # Add extension patterns
    patterns.extend(IGNORE_EXTENSIONS)
    
    return ','.join(patterns) 