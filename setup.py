from setuptools import setup, find_packages

setup(
    name="readdjvu",
    version="0.1.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    entry_points={
        "console_scripts": [
            "readdjvu=readdjvu.cli:main",
        ],
    },
    install_requires=[
        # No Python dependencies, but requires DjVuLibre
    ],
    author="Gemini",
    author_email="",
    description="A tool to parse DjVu files and extract pages and layers.",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/user/readdjvu",  # Placeholder URL
)
