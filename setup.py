import os
from setuptools import setup, find_packages


def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()


setup(
    name="pyswitch",
    version="0.4",
    description="Twisted Protocols for interaction with the FreeSWITCH",
    author="Godeson Gera",
    author_email="godson.g@gmail.com",
    license="GPL",
    keywords="freeswitch eventsocket twisted protocol",
    long_description=read("README.md"),
    install_requires=[
        "Twisted",
    ],
    classifiers=[
        "License :: OSI Approved :: GNU General Public License (GPL)",
        "Programming Language :: Python",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Intended Audience :: Developers",
    ],
    packages=find_packages(),
    package_data={
        # If any package contains *.txt or *.rst files, include them:
        "": ["*.txt", "*.rst"],
        # And include any *.msg files found in the 'pyswitch' package, too:
        "pyswitch": ["*.msg"],
    },
)
