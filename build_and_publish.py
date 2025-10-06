#!/usr/bin/env python3
"""
Build and publish script for inter-service-sdk
Auto-increments version, builds, and publishes to PyPI with automatic dependent project updates
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

# Color codes for output
RED = '\033[0;31m'
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
NC = '\033[0m'  # No Color

def print_colored(message, color=NC):
    """Print colored message"""
    print(f"{color}{message}{NC}")

def run_command(cmd, env_vars=None, capture_output=False):
    """Run command with environment variables"""
    env = os.environ.copy()
    if env_vars:
        env.update(env_vars)

    print_colored(f"Running: {cmd}", YELLOW)

    if capture_output:
        result = subprocess.run(cmd, shell=True, env=env, capture_output=True, text=True)
        return result.returncode == 0, result.stdout
    else:
        result = subprocess.run(cmd, shell=True, env=env)
        return result.returncode == 0

def get_current_version():
    """Get current version from pyproject.toml"""
    with open("pyproject.toml", "r") as f:
        for line in f:
            if line.startswith("version"):
                return line.split('"')[1]
    return "unknown"

def increment_version(version_str):
    """Increment patch version (e.g., 1.0.0 -> 1.0.1)"""
    parts = version_str.split('.')
    if len(parts) == 3:
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
        return f"{major}.{minor}.{patch + 1}"
    return version_str

def update_version_in_files(new_version):
    """Update version in both pyproject.toml and __init__.py"""
    # Update pyproject.toml
    with open("pyproject.toml", "r") as f:
        content = f.read()

    # Replace version line
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if line.startswith("version"):
            lines[i] = f'version = "{new_version}"'
            break

    with open("pyproject.toml", "w") as f:
        f.write('\n'.join(lines))

    # Update __init__.py
    init_file = Path("inter_service_sdk/__init__.py")
    if init_file.exists():
        with open(init_file, "r") as f:
            content = f.read()

        # Replace __version__ line
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if line.startswith("__version__"):
                lines[i] = f'__version__ = "{new_version}"'
                break

        with open(init_file, "w") as f:
            f.write('\n'.join(lines))

    print_colored(f"✅ Updated version to {new_version} in pyproject.toml and __init__.py", GREEN)

def update_dependent_projects(new_version):
    """Update requirements.txt in dependent projects"""
    print_colored(f"\n📝 Updating dependent projects to use inter-service-sdk=={new_version}...", YELLOW)

    projects = [
        ("auto_login", "../auto_login/requirements.txt"),
        ("browser-ninja", "../browser-ninja/requirements.txt")
    ]

    updated_count = 0
    for project_name, req_file in projects:
        req_path = Path(req_file)
        if req_path.exists():
            try:
                # Read the file
                with open(req_path, 'r') as f:
                    content = f.read()

                # Update inter-service-sdk version
                import re
                updated_content = re.sub(
                    r'inter-service-sdk==[\d\.]+',
                    f'inter-service-sdk=={new_version}',
                    content
                )

                # Write back if changed
                if updated_content != content:
                    with open(req_path, 'w') as f:
                        f.write(updated_content)
                    print_colored(f"  ✅ Updated {project_name} requirements.txt", GREEN)
                    updated_count += 1
                else:
                    print_colored(f"  ℹ️ {project_name} requirements.txt already up to date", YELLOW)

            except Exception as e:
                print_colored(f"  ❌ Failed to update {project_name}: {e}", RED)
        else:
            print_colored(f"  ⚠️ {project_name} requirements.txt not found at {req_path}", YELLOW)

    if updated_count > 0:
        print_colored(f"✅ Updated {updated_count} project(s) to use inter-service-sdk=={new_version}", GREEN)
    else:
        print_colored("ℹ️ No project files needed updating", YELLOW)

def clean_build_artifacts():
    """Clean up old build artifacts"""
    print_colored("\n🧹 Cleaning up old builds...", YELLOW)

    dirs_to_remove = ["dist", "build", "*.egg-info"]
    for pattern in dirs_to_remove:
        if "*" in pattern:
            # Handle glob patterns
            for path in Path(".").glob(pattern):
                if path.exists():
                    shutil.rmtree(path)
        else:
            # Handle direct paths
            path = Path(pattern)
            if path.exists():
                shutil.rmtree(path)

    print_colored("✅ Cleaned old build artifacts", GREEN)

def build_package():
    """Build the package"""
    print_colored("\n📦 Building package...", YELLOW)

    # Install build tools
    success = run_command("python -m pip install --upgrade build twine --quiet")
    if not success:
        print_colored("❌ Failed to install build tools!", RED)
        return False

    # Build the package
    success = run_command("python -m build")
    if not success:
        print_colored("❌ Build failed!", RED)
        return False

    print_colored("✅ Package built successfully", GREEN)

    # Show build artifacts
    print_colored("\n📋 Build artifacts:", YELLOW)
    for file in Path("dist").glob("*"):
        size_kb = file.stat().st_size / 1024
        print(f"  - {file.name} ({size_kb:.1f} KB)")

    return True

def publish_package(target="prod"):
    """Publish package to PyPI"""
    try:
        from local import PYPI_API_TOKEN, TEST_PYPI_API_TOKEN
    except ImportError:
        print_colored("❌ Error: local.py not found or missing tokens", RED)
        print("Create local.py with:")
        print('PYPI_API_TOKEN = "your_token_here"')
        print('TEST_PYPI_API_TOKEN = "your_test_token_here"')
        return False

    version = get_current_version()

    if target == "test":
        print_colored(f"\n📤 Publishing version {version} to Test PyPI...", YELLOW)
        env_vars = {
            "TWINE_USERNAME": "__token__",
            "TWINE_PASSWORD": TEST_PYPI_API_TOKEN
        }
        success = run_command("twine upload --repository testpypi dist/*", env_vars)
        if success:
            print_colored(f"\n🎉 Successfully published inter-service-sdk version {version} to Test PyPI!", GREEN)
            print_colored("Install with: pip install -i https://test.pypi.org/simple/ inter-service-sdk", GREEN)
        return success

    elif target == "prod":
        print_colored(f"\n📤 Publishing version {version} to Production PyPI...", YELLOW)
        env_vars = {
            "TWINE_USERNAME": "__token__",
            "TWINE_PASSWORD": PYPI_API_TOKEN
        }
        success = run_command("twine upload dist/*", env_vars)
        if success:
            print_colored(f"\n🎉 Successfully published inter-service-sdk version {version} to PyPI!", GREEN)
            print_colored(f"Install with: pip install inter-service-sdk=={version}", GREEN)
        return success

    else:
        print_colored(f"❌ Invalid target: {target}", RED)
        return False

def main():
    print_colored("🚀 Inter-Service SDK Build and Publish Script", GREEN)
    print_colored("=" * 50, GREEN)

    # Parse arguments
    target = "prod"  # Default to production
    if len(sys.argv) > 1:
        if sys.argv[1] in ["test", "prod"]:
            target = sys.argv[1]
        elif sys.argv[1] in ["--help", "-h"]:
            print("Usage: python build_and_publish.py [test|prod]")
            print("  test - Build and upload to Test PyPI")
            print("  prod - Build and upload to Production PyPI (default)")
            sys.exit(0)
        else:
            print_colored(f"❌ Invalid argument: {sys.argv[1]}", RED)
            print("Use 'test' or 'prod'")
            sys.exit(1)

    current_version = get_current_version()
    new_version = increment_version(current_version)
    print_colored(f"Current version: {current_version}", GREEN)
    print_colored(f"New version: {new_version}", GREEN)

    # Step 0: Auto-increment version
    update_version_in_files(new_version)

    # Step 1: Clean old artifacts
    clean_build_artifacts()

    # Step 2: Build package
    if not build_package():
        sys.exit(1)

    # Step 3: Publish package
    if not publish_package(target):
        print_colored("❌ Failed to publish to PyPI", RED)
        sys.exit(1)

    # Step 4: Update dependent projects
    update_dependent_projects(new_version)

    print_colored("\n✨ Done!", GREEN)

if __name__ == "__main__":
    main()