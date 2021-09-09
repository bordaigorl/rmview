from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *

from rmview.rmparams import *

import paramiko
import struct
import time

import sys
import os
import logging

from twisted.internet.protocol import Protocol
from twisted.internet import protocol, reactor, ssl
from twisted.application import internet, service

from rmview.screenstream.common import *

log = logging.getLogger('rmview')


class ScreenShareStream(QRunnable):

  factory = None

  def __init__(self, ssh):
    super(ScreenShareStream, self).__init__()
    self.ssh = ssh
    self.signals = ScreenStreamSignals()

  def needsDependencies(self):
    return False

  def installDependencies(self):
    pass

  def stop(self):
    log.info("Stopping framebuffer thread...")
    reactor.callFromThread(reactor.stop)

  @pyqtSlot()
  def run(self):
      log.info("Connecting to ScreenShare (make sure it's enabled!)")
      try:
        self.factory = VncFactory(self.signals)
        #left for testing with stunnel
        #self.vncClient = internet.TCPClient("localhost", 31337, self.factory)
        self.vncClient = internet.SSLClient(self.ssh.hostname, 5900, self.factory, ssl.ClientContextFactory())
        self.vncClient.startService()
        reactor.run(installSignalHandlers=0)
      except Exception as e:
        log.error(e)

  @pyqtSlot()
  def pause(self):
    self.signals.blockSignals(True)

  @pyqtSlot()
  def resume(self):
    self.signals.blockSignals(False)
    try:
      self.factory.instance.emitImage()
    except Exception:
      log.warning("Not ready to resume")

  def pointerEvent(self, x, y, button):
    pass

  def keyEvent(self, key):
    pass

  def emulatePressRelease(self, key):
    pass
