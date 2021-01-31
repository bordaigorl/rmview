from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *

from .rmparams import *

import paramiko
import struct
import time

import sys
import os
import logging


from twisted.internet.protocol import Protocol
from twisted.internet import protocol, reactor, threads
from twisted.application import internet, service

from .rfb import *

try:
  IMG_FORMAT = QImage.Format_Grayscale16
except Exception:
  IMG_FORMAT = QImage.Format_RGB16
BYTES_PER_PIXEL = 2

log = logging.getLogger('rmview')

class FBWSignals(QObject):
  onFatalError = pyqtSignal(Exception)
  onNewFrame = pyqtSignal(QImage)


class RFB(RFBClient):
  img = QImage(WIDTH, HEIGHT, IMG_FORMAT)
  painter = QPainter(img)

  def __init__(self, signals):
    super(RFB, self).__init__()
    self.signals = signals

  def emitImage(self):
    self.signals.onNewFrame.emit(self.img)

  def vncConnectionMade(self):
    # self.signals = self.factory.signals
    self.setEncodings([
      HEXTILE_ENCODING,
      CORRE_ENCODING,
      PSEUDO_CURSOR_ENCODING,
      RRE_ENCODING,
      RAW_ENCODING ])
    # time.sleep(.1) # get first image without artifacts
    self.framebufferUpdateRequest()

  def sendPassword(self, password):
    self.signals.onFatalError.emit(Exception("Unsupported password request."))

  def commitUpdate(self, rectangles=None):
    self.signals.onNewFrame.emit(self.img)
    self.framebufferUpdateRequest(incremental=1)

  def updateRectangle(self, x, y, width, height, data):
    self.painter.drawImage(x,y,QImage(data, width, height, width * BYTES_PER_PIXEL, IMG_FORMAT))



class RFBFactory(RFBFactory):
  protocol = RFB
  instance = None

  def __init__(self, signals):
    super(RFBFactory, self).__init__()
    self.signals = signals

  def buildProtocol(self, addr):
    self.instance = RFB(self.signals)
    self.instance.factory = self
    return self.instance

  def clientConnectionLost(self, connector, reason):
    log.warning("Connection lost: %s", reason.getErrorMessage())
    connector.connect()

  def clientConnectionFailed(self, connector, reason):
    self.signals.onFatalError.emit(Exception("Connection failed: " + str(reason)))
    reactor.callFromThread(reactor.stop)


class FrameBufferWorker(QRunnable):

  _stop = False
  vncClient = None
  ignoreEvents = False

  def __init__(self, ssh, delay=None, lz4_path=None, img_format=IMG_FORMAT):
    super(FrameBufferWorker, self).__init__()
    self.ssh = ssh
    self.img_format = img_format

    self.signals = FBWSignals()

  def stop(self):
    self._stop = True
    log.info("Stopping framebuffer thread...")
    try:
      self.vncClient.disconnect()
    except Exception:
      reactor.callFromThread(reactor.stop)
    try:
      self.ssh.exec_command("killall rM-vnc-server-standalone", timeout=3)
    except Exception as e:
      log.warning("VNC could not be stopped on the reMarkable.")
      log.warning("Although this is not a big problem, it may consume some resources until you restart the tablet.")
      log.warning("You can manually terminate it by running `ssh %s killall rM-vnc-server-standalone`.", self.ssh.hostname)
      log.error(e)
    log.info("Framebuffer thread stopped")

  @pyqtSlot()
  def run(self):
    try:
      _,_,out = self.ssh.exec_command("$HOME/rM-vnc-server-standalone")
      log.info(next(out))
    except Exception as e:
      self.signals.onFatalError.emit(e)

    while self._stop == False:
      log.info("Starting VNC server")
      try:
        self.factory = RFBFactory(self.signals)
        self.vncClient = reactor.connectTCP(self.ssh.hostname, 5900, self.factory)
        reactor.run(installSignalHandlers=0)
      except Exception as e:
        log.error(e)

  @pyqtSlot()
  def pause(self):
    self.ignoreEvents = True
    self.signals.blockSignals(True)

  @pyqtSlot()
  def resume(self):
    self.ignoreEvents = False
    self.signals.blockSignals(False)
    try:
      self.factory.instance.emitImage()
    except Exception:
      log.warning("Not ready to pause")

  # @pyqtSlot(int,int,int)
  def pointerEvent(self, x, y, button):
    if self.ignoreEvents: return
    try:
      reactor.callFromThread(self.factory.instance.pointerEvent, x, y, button)
    except Exception as e:
      log.warning("Not ready to send pointer events! [%s]", e)

  def keyEvent(self, key):
    if self.ignoreEvents: return
    reactor.callFromThread(self.factory.instance.keyEvent, key)
    reactor.callFromThread(self.factory.instance.keyEvent, key, 0)


class PWSignals(QObject):
  onFatalError = pyqtSignal(Exception)
  onPenMove = pyqtSignal(int, int)
  onPenPress = pyqtSignal()
  onPenLift = pyqtSignal()
  onPenNear = pyqtSignal()
  onPenFar = pyqtSignal()

LIFTED = 0
PRESSED = 1


class PointerWorker(QRunnable):

  _stop = False

  def __init__(self, ssh, path="/dev/input/event0", threshold=1000):
    super(PointerWorker, self).__init__()
    self.event = path
    self.ssh = ssh
    self.threshold = threshold
    self.signals = PWSignals()

  @pyqtSlot()
  def pause(self):
    self.signals.blockSignals(True)

  @pyqtSlot()
  def resume(self):
    self.signals.blockSignals(False)

  def stop(self):
    self._penkill.write('\n')
    self._stop = True

  @pyqtSlot()
  def run(self):
    penkill, penstream, _ = self.ssh.exec_command('cat %s & { read ; kill %%1; }' % self.event)
    self._penkill = penkill
    new_x = new_y = False
    state = LIFTED

    while not self._stop:
      try:
        _, _, e_type, e_code, e_value = struct.unpack('2IHHi', penstream.read(16))
      except struct.error:
        return
      except Exception as e:
        log.error('Error in pointer worker: %s %s', type(e), e)
        return

      # decoding adapted from remarkable_mouse
      if e_type == e_type_abs:


        # handle x direction
        if e_code == e_code_stylus_xpos:
          x = e_value
          new_x = True

        # handle y direction
        if e_code == e_code_stylus_ypos:
          y = e_value
          new_y = True

        # handle draw
        if e_code == e_code_stylus_pressure:
          if e_value > self.threshold:
            if state == LIFTED:
              log.debug('PRESS')
              state = PRESSED
              self.signals.onPenPress.emit()
          else:
            if state == PRESSED:
              log.debug('RELEASE')
              state = LIFTED
              self.signals.onPenLift.emit()

        if new_x and new_y:
          self.signals.onPenMove.emit(x, y)
          new_x = new_y = False

      if e_type == e_type_key and e_code == e_code_stylus_proximity:
        if e_value == 0:
          self.signals.onPenFar.emit()
        else:
          self.signals.onPenNear.emit()



