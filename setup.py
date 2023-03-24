from setuptools.command.install import install
from setuptools.command.develop import develop
from setuptools.command.egg_info import egg_info

from setuptools import setup, find_packages

import sys

import PyQt6.QtCore as QtCore

def genResources():
    QtCore.QDir.addSearchPath('assets', 'assets/')
    QtCore.QDir.addSearchPath('bin', 'bin/')
    saved_argv = sys.argv
    # Use current environment to find pyrcc but use the public interface
    sys.argv = saved_argv

# https://stackoverflow.com/questions/19569557/pip-not-picking-up-a-custom-install-cmdclass
class genResourcesInstall(install):
    def run(self):
        genResources()
        install.run(self)

class genResourcesDevelop(develop):
    def run(self):
        genResources()
        develop.run(self)

class genResourcesEggInfo(egg_info):
    def run(self):
        genResources()
        egg_info.run(self)

setup(
  name='rmview',
  version='3.0',
  url='https://github.com/bordaigorl/rmview',
  description='rMview: a fast live viewer for reMarkable',
  author='bordaigorl',
  author_email='emanuele.dosualdo@gmail.com',
  classifiers=[
    'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
  ],
  packages=['rmview', 'rmview.screenstream'],
  install_requires=['pyqt6', 'paramiko', 'twisted[tls]', 'pyjwt'],
  extras_require = { 'tunnel': ['sshtunnel'] },
  entry_points={
    'console_scripts':['rmview = rmview.rmview:rmViewMain']
  },
  cmdclass={
    'install': genResourcesInstall,
    'develop': genResourcesDevelop,
    'egg_info': genResourcesEggInfo,
  }
)
