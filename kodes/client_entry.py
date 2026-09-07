"""
PyInstaller entry point.

src/client/main.py uses package-relative imports (e.g. `from ..utils.config ...`);
when executed directly as a script (which is how PyInstaller treats the entry
script) those imports break with "attempted relative import beyond top-level
package". This wrapper imports it from INSIDE the package, so the relative
imports resolve.

Run (from the kodes/ directory): pyinstaller build/client_build.spec
"""
from src.client.main import main

if __name__ == '__main__':
    main()
