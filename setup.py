from setuptools import setup, find_packages

setup(
  name='rmview',
  packages=['rmview'],
  install_requires=['pyqt5', 'paramiko', 'twisted'],
  entry_points={
      'console_scripts':['rmview = rmview.rmview:rmViewMain']
  }
)