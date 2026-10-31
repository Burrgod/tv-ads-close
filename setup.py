#!/usr/bin/env python3
"""Packaging for the optional `tv-ads-close` console command.

The supported path is: clone the repo and run `python3 scripts/tv_ads_close.py`.
This file is optional packaging for people who want a `tv-ads-close` command
on PATH in an environment that already has setuptools/wheel.
"""

import re
from pathlib import Path

from setuptools import setup

ROOT = Path(__file__).resolve().parent
VERSION = re.search(
    r'^VERSION = "([^"]+)"',
    (ROOT / "scripts" / "tv_ads_close.py").read_text(encoding="utf-8"),
    re.MULTILINE,
).group(1)

setup(
    name="tv-ads-close",
    version=VERSION,
    description="Safety-first system-ad control for Xiaomi/Redmi TVs over ADB.",
    long_description=(ROOT / "README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    license="MIT",
    url="https://github.com/Burrgod/tv-ads-close",
    python_requires=">=3.9",
    py_modules=["tv_ads_close"],
    package_dir={"": "scripts"},
    data_files=[
        ("share/tv-ads-close/profiles", ["profiles/schema.json"]),
        ("share/tv-ads-close/profiles/xiaomi", ["profiles/xiaomi/mitv-mfzp0.json"]),
    ],
    entry_points={"console_scripts": ["tv-ads-close=tv_ads_close:main"]},
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: MacOS",
        "Operating System :: POSIX :: Linux",
    ],
)
