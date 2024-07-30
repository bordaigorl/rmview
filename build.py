import sys, os
from PyQt5.pyrcc_main import processResourceFile

def build(_setup_kwargs):
    # Generate resources.py from resources.qrc
    processResourceFile(['resources.qrc'], 'src/rmview/resources.py', False)
