from setuptools.command.install import install
from setuptools.command.develop import develop
from setuptools.command.egg_info import egg_info

from setuptools import setup, find_packages

import sys

def genResources():
    from PyQt5.pyrcc_main import main as pyrcc_main
    saved_argv = sys.argv
    # Use current environment to find pyrcc but use the public interface
    sys.argv = ['pyrcc5', '-o', 'src/rmview/resources.py', 'resources.qrc']
    pyrcc_main()
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
  version='0.1',
  url='https://github.com/bordaigorl/rmview',
  description='rMview: a fast live viewer for reMarkable',
  author='bordaigorl',
  author_email='emanuele.dosualdo@gmail.com',
  classifiers=[
    'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
  ],
  packages=['rmview'],
  install_requires=['pyqt5', 'paramiko', 'twisted'],
  entry_points={
    'console_scripts':['rmview = rmview.rmview:rmViewMain']
  },
  cmdclass={
    'install': genResourcesInstall,
    'develop': genResourcesDevelop,
    'egg_info': genResourcesEggInfo,
  }
)
