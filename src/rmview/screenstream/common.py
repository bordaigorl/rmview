import logging
import atexit

from PyQt5.QtGui import *
from PyQt5.QtCore import *

from twisted.internet import reactor
from twisted.internet.error import ConnectionRefusedError

from ..rmparams import *
from ..rfb import *

try:
  IMG_FORMAT = QImage.Format_Grayscale16
except Exception:
  IMG_FORMAT = QImage.Format_RGB16
BYTES_PER_PIXEL = 2

log = logging.getLogger('rmview')


class ScreenStreamSignals(QObject):
  onFatalError = pyqtSignal(Exception)
  onNewFrame = pyqtSignal(QImage)
  onChallengeReceived = pyqtSignal(bytes)


class VncClient(RFBClient):
  img = QImage(WIDTH, HEIGHT, IMG_FORMAT)
  painter = QPainter(img)

  def __init__(self, signals):
    super(VncClient, self).__init__()
    self.signals = signals

  def emitImage(self):
    self.signals.onNewFrame.emit(self.img)

  def vncConnectionMade(self):
    log.info("Connection to VNC server has been established")

    # self.signals = self.factory.signals
    self.setEncodings([
      HEXTILE_ENCODING,
      CORRE_ENCODING,
      PSEUDO_CURSOR_ENCODING,
      RRE_ENCODING,
      ZRLE_ENCODING,
      RAW_ENCODING ])
    self.framebufferUpdateRequest()

  def sendPassword(self, password):
    self.signals.onFatalError.emit(Exception("Unsupported password request."))

  def commitUpdate(self, rectangles=None):
    self.signals.onNewFrame.emit(self.img)
    self.framebufferUpdateRequest(incremental=1)

  def updateRectangle(self, x, y, width, height, data):
    self.painter.drawImage(x,y,QImage(data, width, height, width * BYTES_PER_PIXEL, IMG_FORMAT))

  def getRMChallenge(self):
    return self.factory.challenge


class VncFactory(RFBFactory):
  protocol = VncClient
  instance = None
  challenge = None #bytes(32)

  def __init__(self, signals):
    super(VncFactory, self).__init__()
    self.signals = signals

  def buildProtocol(self, addr):
    self.instance = VncClient(self.signals)
    self.instance.factory = self
    return self.instance

  def clientConnectionLost(self, connector, reason):
    log.warning("Disconnected: %s", reason.getErrorMessage())
    reactor.callFromThread(reactor.stop)

  def clientConnectionFailed(self, connector, reason):
    if reason.check(ConnectionRefusedError):
      self.signals.onFatalError.emit(Exception("It seems the tablet is refusing to connect.\nIf you are using the ScreenShare backend please make sure you enabled it on the tablet, before running rmview."))
    else:
      self.signals.onFatalError.emit(Exception("Connection failed: " + str(reason)))
    reactor.callFromThread(reactor.stop)

  def setChallenge(self, challenge):
    self.challenge = challenge

