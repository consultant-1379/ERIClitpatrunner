# This should be removed
from setuptools import setup, find_packages
import os

from xml.etree import ElementTree


def _read_pom_version():
    pom = ElementTree.parse(os.path.join(os.path.dirname(__file__), 'pom.xml'))
    root = pom.getroot()
    ver = [ver for ver in root.getchildren() if ver.tag.endswith("}version")]
    ver = ver[0] if ver else None
    return ver.text.split('-')[0] if ver.text else "0.0.0"


setup(
    name='LITP ATs',
    version=_read_pom_version(),
    description='A description.',
    packages=find_packages("src"),
    include_package_data=True,
    package_dir= { '': 'src'},
    scripts=['bin/runats'],
)

