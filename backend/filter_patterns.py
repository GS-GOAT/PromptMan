# Common ignore patterns for file filtering
IGNORE_PATH_PATTERNS = {
    'node_modules', '.git', '__pycache__', '.pytest_cache',
    'venv', 'env', '.env', '.venv', '.idea', '.vscode',
    'build', 'dist', 'target', 'out', 'bin', 'release', 'debug', '__deploy__',
    '_build', 'site', 'public',
    'vendor', 'deps', 'Pods', 'Carthage', 'packages',
    '.history', '.metals', '.bsp'
}

IGNORE_FILE_PATTERNS = {
    'package-lock.json', 'yarn.lock', '.gitignore', '.DS_Store', 'pnpm-lock.yaml',
    # OS-specific junk
    'Thumbs.db'
}

IGNORE_EXTENSIONS = {
    '.pyc', '.pyo', '.pyd', '.so', '.dll', '.dylib',
    '.log', '.tmp', '.temp', '.swp', '.svg', 
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', 
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', 
    '.zip', '.tar.gz', '.rar', '.gz', '.bz2', '.7z', '.iso', '.dmg', '.pkg', '.deb', '.rpm', 
    '.mp3', '.wav', '.ogg', '.mp4', '.mov', '.avi', '.mkv', '.webm', 
    '.pkl', '.parquet', '.hdf5', '.feather', '.arrow', '.csv', '.json', '.xml', '.sqlite', '.db', 
    '.pt', '.pth', '.pb', '.tflite', '.onnx', '.h5', '.keras', 
    '.stl', '.obj', '.fbx', '.dae', '.blend', '.dwg', '.dxf', '.step', '.iges', 
    '.ttf', '.otf', '.woff', '.woff2', '.eot', 
    '.o', 
    '.class', '.jar', '.war', '.ear' 
}

def get_default_exclude_patterns():
    """Returns a comma-separated string of default exclude patterns."""
    patterns = []
    
    # For path patterns, we add a trailing / to match directories
    patterns.extend(f'{p}/' for p in IGNORE_PATH_PATTERNS)
    
    # Add file patterns and extension patterns
    # These match the file name or extension anywhere
    patterns.extend(IGNORE_FILE_PATTERNS)
    patterns.extend(IGNORE_EXTENSIONS)

    # Ensure uniqueness and join
    return ','.join(sorted(list(set(patterns)))) 