from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="livedict",
    version="1.0.4",
    author="Hemanshu Vaidya",
    author_email="hemanshuvaidya64@gmail.com",
    description="Encrypted TTL-based key-value store with sandboxed hooks and optional persistence backends (SQLite/File/Redis).",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/hemanshu03/LiveDict",
    packages=find_packages(exclude=["tests", "tests.*", "docs", "docs.*"]),
    python_requires=">=3.8",
    include_package_data=True,
    install_requires=[
        "pydantic>=1.10",
        "cryptography>=3.4",
        "redis>=4.0",
        "typing-extensions>=4.0",
    ],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
