from setuptools import setup, find_packages

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
  }
)
