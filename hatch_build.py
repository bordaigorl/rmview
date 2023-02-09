from hatchling.builders.hooks.plugin.interface import BuildHookInterface
from PyQt5 import pyrcc_main as pyrcc


class CustomHook(BuildHookInterface):
    def initialize(self, version, build_data):
        pyrcc.processResourceFile(
            filenamesIn=["resources.qrc"],
            filenameOut="src/rmview/resources.py",
            listFiles=False,
        )
