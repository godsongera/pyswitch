#!/usr/bin/env python
"""Installs PySWITCH using distutils

Run:
	python setup.py install
to install the package from the source archive.
"""


def npFilesFor(dirname):
    """Return all non-python-file filenames in dir"""
    result = []
    allResults = []
    for name in os.listdir(dirname):
        path = os.path.join(dirname, name)
        if os.path.isfile(path) and os.path.splitext(name)[1] not in ('.py', '.pyc', '.pyo'):
            result.append(path)
        elif os.path.isdir(path) and name.lower() != 'cvs':
            allResults.extend(npFilesFor(path))
    if result:
        allResults.append((dirname, result))
    return allResults


##############
## Following is from Pete Shinners,
## apparently it will work around the reported bug on
## some unix machines where the data files are copied
## to weird locations if the user's configuration options
## were entered during the wrong phase of the moon :) .


from distutils.command.install_data import install_data


class smart_install_data(install_data):
    def run(self):
        # need to change self.install_dir to the library dir
        install_cmd = self.get_finalized_command('install')
        self.install_dir = getattr(install_cmd, 'install_lib')
        # should create the directory if it doesn't exist!!!
        return install_data.run(self)


if __name__ == "__main__":
    from distutils.sysconfig import *
    from distutils.core import setup

    dataFiles = npFilesFor('doc') + npFilesFor('examples') + [('.', ('license.txt',))]
    dataFiles = [(os.path.join('pyswitch', directory), files) for (directory, files) in dataFiles]

    from sys import hexversion

    if hexversion >= 0x2030000:
        # work around distutils complaints under Python 2.2.x
        extraArguments = {
            'classifiers': [
                """License :: OSI Approved :: GNU General Public License (GPL)""",
                """Programming Language :: Python""",
                """Topic :: Software Development :: Libraries :: Python Modules""",
                """Intended Audience :: Developers""",
            ],
            'keywords': 'freeswitch,eventsocekt,twisted,protocol,',
            'long_description': """Twisted Protocols for interaction with FreeSWITCH

			Provides EventSocket protocol under Twisted,
			allowing for fairly extensive customisation of FreeSWITCH operations
			from a Twisted process.""",
            'platforms': ['Any'],
        }
    else:
        extraArguments = {}

    setup(
        name="pyswitch",
        version='0.3',
        url="http://pyswitch.sf.net",
        download_url="https://sourceforge.net/projects/pyswitch/files/",
        description="Twisted Protocols for interaction with the FreeSWITCH",
        author="Godson Gera",
        author_email="godson.g@gmail.com",
        license="GPL",

        package_dir={
            'pyswitch': '.',
        },
        packages=[
            'pyswitch',
            'pyswitch.examples',
        ],
        options={
            'sdist': {'force_manifest': 1, 'formats': ['gztar', 'zip'],},
        },
        data_files=dataFiles,
        cmdclass={'install_data': smart_install_data},
        **extraArguments)
