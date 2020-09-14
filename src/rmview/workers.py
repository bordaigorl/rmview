from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *

from .rmparams import *
from .installparams import *

import paramiko
import struct
import time

import sys
import os
import logging


from twisted.internet.protocol import Protocol
from twisted.internet import protocol, reactor
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


class RFBTest(RFBClient):
  img = QImage(WIDTH, HEIGHT, IMG_FORMAT)
  painter = QPainter(img)

  def vncConnectionMade(self):
    self.signals = self.factory.signals
    self.setEncodings([
      HEXTILE_ENCODING,
      CORRE_ENCODING,
      RRE_ENCODING,
      RAW_ENCODING ])
    self.framebufferUpdateRequest()

  def sendPassword(self, password):
    self.signals.onFatalError.emit(Exception("Unsupported password request."))

  def commitUpdate(self, rectangles=None):
    self.signals.onNewFrame.emit(self.img)
    self.framebufferUpdateRequest(incremental=1)

  def updateRectangle(self, x, y, width, height, data):
    self.painter.drawImage(x,y,QImage(data, width, height, width * BYTES_PER_PIXEL, IMG_FORMAT))



class RFBTestFactory(RFBFactory):
  """test factory"""
  protocol = RFBTest

  def __init__(self, signals):
    super(RFBTestFactory, self).__init__()
    self.signals = signals

  def clientConnectionLost(self, connector, reason):
    log.warning("Connection lost: %s", reason.getErrorMessage())
    connector.connect()

  def clientConnectionFailed(self, connector, reason):
    self.signals.onFatalError.emit(Exception("Connection failed: " + str(reason)))
    reactor.callFromThread(reactor.stop)


class FrameBufferWorker(QRunnable):

  _stop = False

  def __init__(self, ssh, delay=None, lz4_path=None, img_format=IMG_FORMAT):
    super(FrameBufferWorker, self).__init__()
    self.ssh = ssh
    self.img_format = img_format

    self.signals = FBWSignals()

  def stop(self):
    log.info("Stopping framebuffer thread...")
    reactor.callFromThread(reactor.stop)
    self.ssh.exec_command("killall rM-vnc-server")
    log.info("Framebuffer thread stopped")
    self._stop = True

  def _downloadAndCheckFile(self, url, filename, sha1sum, executable = False):
    _,_,out = self.ssh.exec_command("wget " + url + " -O " + filename)
    log.debug("wget returned %d", out.channel.recv_exit_status())

    _,out,_ = self.ssh.exec_command("sha1sum " + filename)
    log.debug("sha1sum returned %d", out.channel.recv_exit_status())
    sha1sum_out = out.read().decode("utf-8")

    if sha1sum_out[:40] != sha1sum:
      error_msg = "Mismatched SHA1 sum in download from " + url
      # Delete the file so a second run won't pass
      _,_,out = self.ssh.exec_command("rm " + filename)
      log.debug("rm returned %d", out.channel.recv_exit_status())
      # TODO: Download to a temporary and move instead of deleting
      raise RuntimeError(error_msg)

    if executable:
      _,_,out = self.ssh.exec_command("chmod 0755 " + filename)
      log.debug("chmod returned %d", out.channel.recv_exit_status())

  @pyqtSlot()
  def run(self):
    try:
      
      _,out,_ = self.ssh.exec_command("ls -1")
      file_list = out.read().decode("utf-8").split("\n")
      if not "mxc_epdc_fb_damage.ko" in file_list:
        log.info("mxc_epdc_fb_damage.ko not found. Downloading...")
        self._downloadAndCheckFile(kernel_mod_url, 'mxc_epdc_fb_damage.ko', kernel_mod_hash)

      if not "rM-vnc-server" in file_list:
        log.info("rM-vnc-server not found. Downloading...")
        self._downloadAndCheckFile(vncserver_url, 'rM-vnc-server', vncserver_hash, executable=True)
        
      # Should we always checksum this kernel module before attempting to load?
      # An incomplete wget will leave some partial file around
      _,out,_ = self.ssh.exec_command("cat /proc/cpuinfo")
      log.debug("Cat returned %d", out.channel.recv_exit_status())
      cpuinfo = out.read().decode("utf-8").split("\n")[10]

      # Make sure this is a Remarkable V1 before attempting to load the kernel module
      if not 'Freescale i.MX6 SoloLite' in cpuinfo:
        raise RuntimeError("Unexpected processor. Is this a Remarkable v1?")

      _,out,_ = self.ssh.exec_command("/sbin/insmod $HOME/mxc_epdc_fb_damage.ko")
      log.debug("Insmod returned %d", out.channel.recv_exit_status())
      _,_,out = self.ssh.exec_command("$HOME/rM-vnc-server")
      log.info(next(out))
      self.vncClient = internet.TCPClient(self.ssh.hostname, 5900, RFBTestFactory(self.signals))
      self.vncClient.startService()
      reactor.run(installSignalHandlers=0)
    except Exception as e:
      self.signals.onFatalError.emit(e)

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

  def __init__(self, ssh, threshold=1000):
    super(PointerWorker, self).__init__()
    self.ssh = ssh
    self.threshold = threshold
    self.signals = PWSignals()

  def stop(self):
    self._penkill.write('\n')
    self._stop = True

  @pyqtSlot()
  def run(self):
    penkill, penstream, _ = self.ssh.exec_command('cat /dev/input/event0 & { read ; kill %1; }')
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



