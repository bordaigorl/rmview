from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *

from rmparams import *

import paramiko
import struct
import time

import sys
import os
import logging
log = logging.getLogger('rmview')


from twisted.internet.protocol import Protocol
from twisted.internet import protocol
from twisted.application import internet, service

from vncdotool.rfb import *

try:
  GRAY16 = QImage.Format_Grayscale16
except Exception:
  GRAY16 = QImage.Format_RGB16
RGB16 = QImage.Format_RGB16


SHOW_FPS = False

class FBWSignals(QObject):
  onFatalError = pyqtSignal(Exception)
  onNewFrame = pyqtSignal(QImage)

class RFBTest(RFBClient):
  img = QImage(WIDTH, HEIGHT, GRAY16)
  # bla = 0

  def vncConnectionMade(self):
    self.signals = self.factory.signals
    self.setEncodings([RAW_ENCODING])
    self.framebufferUpdateRequest()

  def commitUpdate(self, rectangles=None):
    self.signals.onNewFrame.emit(self.img)
    self.framebufferUpdateRequest(incremental=1)

  def updateRectangle(self, x, y, width, height, data):
    # print("RECT: ", x, y, width, height, data[:20])
    # c = qRgb(self.bla,self.bla,self.bla)
    # self.bla += 5
    # print(width, WIDTH , height, HEIGHT, (width == WIDTH) and (height == HEIGHT))
    if (width == WIDTH) and (height == HEIGHT):
      print("bulk")
      self.img = QImage(data, WIDTH, HEIGHT, WIDTH * 2, GRAY16)
    else:
      for a in range(width):
        for b in range(height):
          # print(a,b,data[:10])
          c = data[2*(a+(b*width))] + data[2*(a+(b*width))+1]
          self.img.setPixel(x+a,y+b,qRgb(c,c,c)) # data[a+(b*width)]



class RFBTestFactory(RFBFactory):
  """test factory"""
  protocol = RFBTest

  def __init__(self, signals):
    super(RFBTestFactory, self).__init__()
    self.signals = signals

  def clientConnectionLost(self, connector, reason):
    print(reason)
    # connector.connect()

  def clientConnectionFailed(self, connector, reason):
    print("connection failed:", reason)
    from twisted.internet import reactor
    reactor.callFromThread(reactor.stop)


class FrameBufferWorker(QRunnable):

  _stop = False

  def __init__(self, ssh, delay=None, lz4_path=None, img_format=GRAY16):
    super(FrameBufferWorker, self).__init__()
    self._read_loop = """\
      while dd if=/dev/fb0 count=1 bs={bytes} 2>/dev/null; do {delay}; done | {lz4_path}\
    """.format(bytes=TOTAL_BYTES,
               delay="sleep "+str(delay) if delay else "true",
               lz4_path=lz4_path or "$HOME/lz4")
    self.ssh = ssh
    self.img_format = img_format

    self.signals = FBWSignals()

  def stop(self):
    from twisted.internet import reactor
    print("Stopping")
    reactor.callFromThread(reactor.stop)
    self.ssh.exec_command("killall rM-vnc-server")
    print("Stopped")
    self._stop = True

  @pyqtSlot()
  def run(self):
    _,_,out = self.ssh.exec_command("$HOME/rM-vnc-server")
    for line in out:
      print("STARTED", line)
      break
    self.vncClient = internet.TCPClient("192.168.1.111", 5900, RFBTestFactory(self.signals))
    from twisted.internet import reactor
    self.vncClient.startService()
    reactor.run(installSignalHandlers=0)

    # _, rmstream, rmerr = self.ssh.exec_command(self._read_loop)

    # data = b''
    # if SHOW_FPS:
    #   f = 0
    #   t = time.perf_counter()
    #   fps = 0

    # try:
    #   for chunk in Decompressor(rmstream):
    #     data += chunk
    #     while len(data) >= TOTAL_BYTES:
    #       pix = data[:TOTAL_BYTES]
    #       data = data[TOTAL_BYTES:]
    #       self.signals.onNewFrame.emit(QImage(pix, WIDTH, HEIGHT, WIDTH * 2, self.img_format))
    #       if SHOW_FPS:
    #         f += 1
    #         if f % 10 == 0:
    #           fps = 10 / (time.perf_counter() - t)
    #           t = time.perf_counter()
    #         print("FRAME %d  |  FPS %.3f\r" % (f, fps), end='')
    #     if self._stop:
    #       log.debug('Stopping framebuffer worker')
    #       break
    # except Lz4FramedNoDataError:
    #   e = rmerr.read().decode('ascii')
    #   s = rmstream.channel.recv_exit_status()
    #   if s == 127:
    #     log.info("Check if your remarkable has lz4 installed! %s", e)
    #     self.signals.onFatalError.emit(Exception(e))
    #   else:
    #     log.warning("Frame data stream is empty.\nExit status: %d %s", s, e)

    # except Exception as e:
    #   log.error("Error: %s %s", type(e), e)
    #   self.signals.onFatalError.emit(e)



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
        # log.error('Error in pointer worker: %s %s', type(e), e)
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
              # log.debug('PRESS')
              state = PRESSED
              self.signals.onPenPress.emit()
          else:
            if state == PRESSED:
              # log.debug('RELEASE')
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



