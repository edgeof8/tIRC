#!/usr/bin/env python3
"""
Build script for PyRC - handles both package creation and executable building.
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# Build configuration
PACKAGE_NAME = "pyrc"
VERSION = "0.1.0"
DIST_DIR = Path("dist")
BUILD_DIR = Path("build")

def run_command(cmd, cwd=None):
    """Run a command and return its output."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            check=True,
            text=True,
            capture_output=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {' '.join(cmd)}")
        print(f"Error: {e.stderr}")
        sys.exit(1)

def clean_build_dirs():
    """Clean build and dist directories."""
    for dir_path in [BUILD_DIR, DIST_DIR]:
        if dir_path.exists():
            shutil.rmtree(dir_path)
    print("Cleaned build directories")

def build_package():
    """Build the Python package (wheel and source distribution)."""
    print("Building Python package...")
    run_command([sys.executable, "-m", "build"])
    print("Package built successfully")

def build_executable():
    """Build standalone executable using PyInstaller."""
    print("Building standalone executable...")

    # Platform-specific settings
    system = platform.system().lower()
    if system == "windows":
        exe_name = f"{PACKAGE_NAME}-{VERSION}-win64.exe"
        icon = None  # Add icon path if available
    elif system == "darwin":
        exe_name = f"{PACKAGE_NAME}-{VERSION}-macos"
        icon = None  # Add icon path if available
    else:  # Linux
        exe_name = f"{PACKAGE_NAME}-{VERSION}-linux"
        icon = None

    # PyInstaller command
    cmd = [
        "pyinstaller",
        "--name", exe_name,
        "--onefile",
        "--clean",
        "--noconfirm",
        "--add-data", f"pyterm_irc_config.ini.example{os.pathsep}.",
        "--add-data", f"scripts{os.pathsep}scripts",
        "--add-data", f"commands{os.pathsep}commands",
        "--hidden-import", "curses",
        "--hidden-import", "windows-curses",
        "--hidden-import", "pyfiglet",
    ]

    if icon:
        cmd.extend(["--icon", icon])

    # Add main script
    cmd.append("pyrc.py")

    # Run PyInstaller
    run_command(cmd)
    print(f"Executable built: {exe_name}")

def main():
    """Main build function."""
    # Ensure we're in the project root
    if not Path("pyrc.py").exists():
        print("Error: Must run build script from project root directory")
        sys.exit(1)

    # Clean build directories
    clean_build_dirs()

    # Install build dependencies
    print("Installing build dependencies...")
    run_command([sys.executable, "-m", "pip", "install", "-U", "pip", "build", "pyinstaller"])

    # Build package
    build_package()

    # Build executable
    build_executable()

    print("\nBuild completed successfully!")
    print(f"Package files are in: {DIST_DIR}")
    print(f"Executable is in: {DIST_DIR}")

if __name__ == "__main__":
    main()
