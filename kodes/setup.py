import os
from setuptools import setup, find_packages

_here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_here, "..", "README.md"), "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="rinp-kodes-m365-stealer",
    version="1.0.0",
    author="Red in Pulse - Mr.Gedik",
    description="Kodes M365 Red Team - device-code phishing, token harvesting and M365 data collection platform",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "Flask>=2.0.1,<3.0.0",
        "Flask-SQLAlchemy>=2.5.1,<3.0.0",
        "SQLAlchemy>=1.4.0,<2.0.0",
        "PyJWT>=2.1.0,<3.0.0",
        "cryptography>=41.0.0",
        "humanize>=4.0.0,<5.0.0",
        "requests>=2.25.0",
        "pyngrok>=5.0.0",
        "pyautogui>=0.9.50",
        "pyperclip>=1.8.0",
    ],
    entry_points={
        "console_scripts": [
            "kodes=src.main:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.6",
)