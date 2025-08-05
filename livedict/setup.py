from setuptools import setup, find_packages

setup(
    name="livedict",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "cryptography>=3.4",
        "redis>=4.0"
    ],
    python_requires=">=3.8",
    description="Encrypted TTL-based key-value store with sandboxed hooks and optional Redis support.",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="Hemanshu Vaidya",
    url="https://github.com/hemanshu03/LiveDict",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
        "License :: OSI Approved :: MIT License"
    ],
)
