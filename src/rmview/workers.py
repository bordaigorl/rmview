from typing import Tuple

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
    log.warning("Disconnected: %s", reason.getErrorMessage())
    reactor.callFromThread(reactor.stop)

  def clientConnectionFailed(self, connector, reason):
    self.signals.onFatalError.emit(Exception("Connection failed: " + str(reason)))
    reactor.callFromThread(reactor.stop)


class FrameBufferWorker(QRunnable):

  _stop = False

  ignoreEvents = False
  factory = None
  vncClient = None
  sshTunnel = None

  def __init__(self, ssh, ssh_config, delay=None, lz4_path=None, img_format=IMG_FORMAT):
    super(FrameBufferWorker, self).__init__()
    self.ssh = ssh
    self.ssh_config = ssh_config
    self.img_format = img_format
    self.use_ssh_tunnel = self.ssh_config.get("tunnel", False)

    self._vnc_server_already_running = False

    self.signals = FBWSignals()

  def stop(self):
    if self._stop:
        # Already stopped
        return

    self._stop = True

    log.debug("Stopping framebuffer thread...")

    if self.vncClient:
      try:
        log.info("Disconnecting from VNC server...")
        reactor.callFromThread(self.vncClient.stopService)
      except Exception as e:
        log.debug("Disconnect failed (%s), stopping reactor" % str(e))
        reactor.callFromThread(reactor.stop)

    # If we used an existing running instance and didn't start one ourselves we will not kill it.
    if not self._vnc_server_already_running:
      try:
        log.info("Stopping VNC server...")
        self.ssh.exec_command("killall -SIGINT rM-vnc-server-standalone")
      except Exception as e:
        log.warning("VNC could not be stopped on the reMarkable.")
        log.warning("Although this is not a big problem, it may consume some resources until you restart the tablet.")
        log.warning("You can manually terminate it by running `ssh root@%s killall rM-vnc-server-standalone`.", self.ssh.hostname)
        log.error(e)

    if self.sshTunnel:
      try:
        log.info("Stopping SSH tunnel...")
        self.sshTunnel.stop()
      except Exception as e:
        log.error(e)

    log.debug("Framebuffer thread stopped")

  @pyqtSlot()
  def run(self):
    try:
      self._start_vnc_server()
      vnc_server_host, vnc_server_port = self._setup_ssh_tunnel_if_configured()
    except Exception as e:
      self.signals.onFatalError.emit(e)
      return

    log.info("Establishing connection to remote VNC server on %s:%s" % (vnc_server_host,
                                                                        vnc_server_port))
    try:
      self.factory = RFBFactory(self.signals)
      self.vncClient = internet.TCPClient(vnc_server_host, vnc_server_port, self.factory)
      self.vncClient.startService()
      reactor.run(installSignalHandlers=0)
    except Exception as e:
      log.error("Failed to connect to the VNC server: %s" % (str(e)))

  def _check_vnc_server_is_already_running(self) -> bool:
    """
    Check if VNC server is already running on reMarkable.

    If it is, True is returned by this method and a log message if emitted.
    """
    _, stdout, stderr = self.ssh.exec_command("ps -ww | grep rM-vnc-server-standalone | grep -v grep")

    stdout_bytes = stdout.read()

    if b"rM-vnc-server-standalone" in stdout_bytes:
      # TODO: Add config option to force kill and start a fresh server in this case
      vnc_server_already_running = True
      log.info("Found an existing instance of rM-vnc-server-standalone process on reMarkable. "
               "Will try to use that instance instead of starting a new one.")

      if self.use_ssh_tunnel and b"-listen localhost" not in stdout_bytes:
        # If user has configured SSH tunnel, but existing VNC server instance is not using "-listen
        # localhost" flag this likely indicates that the running server is listening on all the
        # interfaces. This could pose a security risk so we log a warning.
        log.warn("Existing VNC server is not running with \"-listen localhost\" flag. This means "
                 "that the existing server is likely listening on all the interfaces. This could "
                 "pose a security risk so you are advised to run server with \"-listen localhost\" "
                 "flag when using an SSH tunnel.")
    else:
      vnc_server_already_running = False

    return vnc_server_already_running

  def _start_vnc_server(self):
    """
    Start VNC server on reMarkable if it's not already running.
    """
    self._vnc_server_already_running = self._check_vnc_server_is_already_running()

    if self._vnc_server_already_running:
      # Server already running, we will try to use that instance
      return

    if self.use_ssh_tunnel:
      # If using SSH tunnel, we ensure VNC server only listens on localhost. That's important for
      # security reasons.
      server_run_cmd = "$HOME/rM-vnc-server-standalone -listen localhost"
    else:
      server_run_cmd = "$HOME/rM-vnc-server-standalone"

    log.info("Starting VNC server (command=%s)" % (server_run_cmd))

    _, _, stdout = self.ssh.exec_command(server_run_cmd)

    # TODO: This method for consuming stdout is not really good, it assumed there will always be
    # at least one line produced...
    # And we should also check exit code and not stdout for better robustness.
    stdout_bytes = next(stdout).strip()
    log.info("Start command stdout output: %s" % (stdout_bytes))

    if "listening for vnc connections on" not in stdout_bytes.lower():
      raise Exception("Failed to start VNC server on reMarkable: %s" % (stdout_bytes))

    # Register atexit handler to ensure we always try to kill started server on exit
    atexit.register(self.stop)


  def _setup_ssh_tunnel_if_configured(self) -> Tuple[str, int]:
    """
    Set up and start SSH tunnel (if configured).
    """
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


    return (vnc_server_host, vnc_server_port)

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

      try:
        import sshtunnel
      except ModuleNotFoundError:
        raise Exception("You need to install `sshtunnel` to use the tunnel feature")
      tunnel = sshtunnel.open_tunnel(
        (self.ssh.hostname, 22),
        remote_bind_address=("127.0.0.1", 5900),
        # We don't specify port so library auto assigns random unused one in the high range
        local_bind_address=('127.0.0.1',),
        compression=self.ssh_config.get("tunnel_compression", False),
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
