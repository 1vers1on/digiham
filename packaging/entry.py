"""Frozen-app entry point.

PyInstaller needs a real script to analyze; this just hands off to the normal
console-script entry point so the frozen build and ``digiham`` on PATH behave
identically.
"""

from digiham.main import main

if __name__ == "__main__":
    main()
