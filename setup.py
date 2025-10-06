"""
Setup configuration for inter-service-sdk.
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read README for long description
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text(encoding="utf-8")

setup(
    name="inter-service-sdk",
    version="1.0.1",
    author="Blazel",
    author_email="dev@blazel.com",
    description="Complete framework for inter-service communication with client, server utilities, auth and encryption",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/AlexanderRyzhko/inter-service-sdk",
    project_urls={
        "Bug Tracker": "https://github.com/AlexanderRyzhko/inter-service-sdk/issues",
        "Documentation": "https://github.com/AlexanderRyzhko/inter-service-sdk#readme",
        "Source Code": "https://github.com/AlexanderRyzhko/inter-service-sdk",
    },
    packages=find_packages(exclude=["tests", "tests.*", "examples"]),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Security :: Cryptography",
    ],
    python_requires=">=3.8",
    install_requires=[
        "requests>=2.31.0",
        "fastapi>=0.104.0",
    ],
    extras_require={
        "crypto": [
            "cryptography>=41.0.0",
        ],
        "dev": [
            "pytest>=7.4.0",
            "pytest-cov>=4.1.0",
            "pytest-mock>=3.11.1",
            "requests-mock>=1.11.0",
            "black>=23.0.0",
            "flake8>=6.1.0",
            "mypy>=1.5.0",
            "types-requests>=2.31.0",
            "build>=1.0.0",
            "twine>=4.0.0",
            "cryptography>=41.0.0",
        ],
    },
    keywords=[
        "http",
        "client",
        "server",
        "api",
        "rest",
        "fastapi",
        "inter-service",
        "microservices",
        "authentication",
        "encryption",
        "ecc",
        "bearer-token",
    ],
    license="MIT",
)