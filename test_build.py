#!/usr/bin/env python3
"""
Test script to validate PyRC package and executable builds.
"""

import os
import platform
import subprocess
import sys
from pathlib import Path

def run_command(cmd, cwd=None):
    """Run a command and return its output."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=30
        )
        return result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return None, "Command timed out"
    except subprocess.CalledProcessError as e:
        return None, f"Error: {e.stderr}"

def test_package_installation():
    """Test installing the package via pip."""
    print("\nTesting package installation...")

    # Install the package
    stdout, stderr = run_command([
        sys.executable, "-m", "pip", "install", "."
    ])

    if stderr:
        print(f"Package installation failed: {stderr}")
        return False

    # Test running pyrc --help
    stdout, stderr = run_command(["pyrc", "--help"])
    if stderr:
        print(f"Running pyrc failed: {stderr}")
        return False

    print("Package installation test passed!")
    return True

def test_executable():
    """Test the standalone executable."""
    print("\nTesting standalone executable...")

    # Find the executable
    system = platform.system().lower()
    if system == "windows":
        exe_pattern = "pyrc-*-win64.exe"
    elif system == "darwin":
        exe_pattern = "pyrc-*-macos"
    else:  # Linux
        exe_pattern = "pyrc-*-linux"

    exe_files = list(Path("dist").glob(exe_pattern))
    if not exe_files:
        print("No executable found!")
        return False

    exe_path = exe_files[0]

    # Test running the executable
    stdout, stderr = run_command([str(exe_path), "--help"])
    if stderr:
        print(f"Running executable failed: {stderr}")
        return False

    print("Executable test passed!")
    return True

def test_headless_mode():
    """Test headless mode functionality."""
    print("\nTesting headless mode...")

    # Test with Python package
    stdout, stderr = run_command(["pyrc", "--headless", "--help"])
    if stderr:
        print(f"Headless mode test failed: {stderr}")
        return False

    print("Headless mode test passed!")
    return True

def test_config_file():
    """Test configuration file handling."""
    print("\nTesting configuration file...")

    # Check if example config exists
    if not Path("pyterm_irc_config.ini.example").exists():
        print("Example config file not found!")
        return False

    # Check if logs directory is created
    if not Path("logs").exists():
        print("Logs directory not created!")
        return False

    print("Configuration file test passed!")
    return True

def main():
    """Run all tests."""
    print("Starting PyRC build validation tests...")

    tests = [
        ("Package Installation", test_package_installation),
        ("Executable", test_executable),
        ("Headless Mode", test_headless_mode),
        ("Configuration File", test_config_file),
    ]

    all_passed = True
    for test_name, test_func in tests:
        print(f"\nRunning {test_name} test...")
        if not test_func():
            all_passed = False
            print(f"{test_name} test failed!")

    if all_passed:
        print("\nAll tests passed successfully!")
        sys.exit(0)
    else:
        print("\nSome tests failed!")
        sys.exit(1)

if __name__ == "__main__":
    main()
