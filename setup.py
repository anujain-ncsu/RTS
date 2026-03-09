from setuptools import setup, find_packages

setup(
    name="rts",
    version="0.1.0",
    description="Relevant Test Selector - predict which tests to run for a given diff",
    author="RTS",
    python_requires=">=3.9",
    packages=find_packages(exclude=["tests", "tests.*"]),
    install_requires=[
        "click>=8.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0",
            "pytest-cov",
        ],
    },
    entry_points={
        "console_scripts": [
            "rts=rts.cli:cli",
        ],
    },
)
