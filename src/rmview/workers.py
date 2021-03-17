from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *

from .rmparams import *

import paramiko
import sshtunnel
import struct
import time

import sys
import os
import logging
import atexit

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
    log.info("Connection to VNC server has been established")

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
    reactor.callFromThread(reactor.stop)

  def clientConnectionFailed(self, connector, reason):
    self.signals.onFatalError.emit(Exception("Connection failed: " + str(reason)))
    reactor.callFromThread(reactor.stop)


class FrameBufferWorker(QRunnable):

  _stop = False
  ignoreEvents = False

  def __init__(self, ssh, ssh_config, delay=None, lz4_path=None, img_format=IMG_FORMAT):
    super(FrameBufferWorker, self).__init__()
    self.ssh = ssh
    self.ssh_config = ssh_config
    self.img_format = img_format
    self.use_ssh_tunnel = self.ssh_config.get("tunnel", False)

    self.factory = None
    self.vncClient = None
    self.sshTunnel = None

    self.signals = FBWSignals()

  def stop(self):
    if self._stop:
        # Already stopped
        return

    self._stop = True

    log.info("Stopping framebuffer thread...")

    try:
      log.info("Disconnecting from VNC server...")
      reactor.callFromThread(self.vncClient.disconnect)
    except Exception:
      reactor.callFromThread(reactor.stop)

    try:
      log.info("Stopping VNC server...")
      self.ssh.exec_command("killall -SIGINT rM-vnc-server-standalone")
    except Exception as e:
      log.warning("VNC could not be stopped on the reMarkable.")
      log.warning("Although this is not a big problem, it may consume some resources until you restart the tablet.")
      log.warning("You can manually terminate it by running `ssh %s killall rM-vnc-server-standalone`.", self.ssh.hostname)
      log.error(e)

    if self.sshTunnel:
      try:
        log.info("Stopping SSH tunnel...")
        self.sshTunnel.stop()
      except Exception as e:
        log.error(e)

    log.info("Framebuffer thread stopped")

  @pyqtSlot()
  def run(self):
    # Check if an existing instance of server is running and for now if it is log a warning and
    # try to re-use that instance
    _, stdout, stderr = self.ssh.exec_command("ps | grep rM-vnc-server-standalone | grep -v grep",
                                              get_pty=True, timeout=3)

    if b"rM-vnc-server-standalone" in stdout.read():
      # TODO: Add config option to force kill and start a fresh server in this case
      vnc_server_already_running = True
      log.warn("Found an existing instance of rM-vnc-server-standalone process on reMarkable. "
                 "Will try to use that instance instead of starting a new one.")

      # TODO: Warn if ssh tunnel is configured, but existing instance is not using "-listen
      # localhost" flag, this would indicate that VNC server is listening on all interfaces which
      # can pose a security risk
    else:
      vnc_server_already_running = False

    if not vnc_server_already_running:
      # If using SSH tunnel, we ensure VNC server only listens on localhost
      if self.use_ssh_tunnel:
        server_run_cmd = "$HOME/rM-vnc-server-standalone -listen localhost"
      else:
        server_run_cmd = "$HOME/rM-vnc-server-standalone"

      log.info("Starting VNC server (command=%s)" % (server_run_cmd))

      try:
        _,_,out = self.ssh.exec_command(server_run_cmd)
        log.info("Start command output: %s" % (next(out).strip()))
      except Exception as e:
        self.signals.onFatalError.emit(e)
        return

    # Register atexit handler to ensure we always try to kill started server on exit
    atexit.register(self.stop)

    if self.use_ssh_tunnel:
        tunnel = self._get_ssh_tunnel()
        tunnel.start()

        self.sshTunnel = tunnel

        log.info("Setting up SSH tunnel %s:%s (rm) <-> %s:%s (localhost)" % ("127.0.0.1", 5900,
                                                                             tunnel.local_bind_host,
                                                                             tunnel.local_bind_port))

        vnc_server_host = tunnel.local_bind_host
        vnc_server_port = tunnel.local_bind_port
    else:
        vnc_server_host = self.ssh.hostname
        vnc_server_port = 5900

    while not self._stop:
        log.info("Establishing connection to remote VNC server on %s:%s" % (vnc_server_host,
                                                                            vnc_server_port))
        try:
            self.factory = RFBFactory(self.signals)
            self.vncClient = internet.TCPClient(vnc_server_host, vnc_server_port, self.factory)
            self.vncClient.startService()
            reactor.run(installSignalHandlers=0)
        except Exception as e:
            log.error("Failed to connect to the VNC server: %s" % (str(e)))

  def _get_ssh_tunnel(self):
      open_tunnel_kwargs = {
        "ssh_username" : self.ssh_config.get("username", "root"),
      }

      if self.ssh_config.get("auth_method", "password") == "key":
          open_tunnel_kwargs["ssh_pkey"] = self.ssh_config["key"]

          if self.ssh_config.get("password", None):
            open_tunnel_kwargs["ssh_private_key_password"] = self.ssh_config["password"]
      else:
        open_tunnel_kwargs["ssh_password"] = self.ssh_config["password"]

      tunnel = sshtunnel.open_tunnel(
        (self.ssh.hostname, 22),
        remote_bind_address=("127.0.0.1", 5900),
        # We don't specify port so library auto assigns random unused one in the high range
        local_bind_address=('127.0.0.1',),
        compression=self.ssh_config.get("tunnel_compression", True),
        **open_tunnel_kwargs)

      return tunnel

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
    reactor.callFromThread(self.emulatePressRelease, key)

  def emulatePressRelease(self, key):
    self.factory.instance.keyEvent(key)
    # time.sleep(.1)
    self.factory.instance.keyEvent(key, 0)


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



