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
import configparser
import jwt
import io
import socket
import hashlib
from twisted.internet.protocol import Protocol,DatagramProtocol
from twisted.internet import protocol, reactor, ssl
from twisted.application import internet, service


from .common import *

log = logging.getLogger('rmview')



class ScreenShareStream(QRunnable):

  factory = None

  def __init__(self, ssh):
    super(ScreenShareStream, self).__init__()
    self.ssh = ssh
    self.signals = ScreenStreamSignals()

  def needsDependencies(self):
    _, out, _ = self.ssh.exec_command("[ -x /usr/bin/nc.traditional ]")
    return out.channel.recv_exit_status() != 0

  def installDependencies(self):
    sftp = self.ssh.open_sftp()
    from stat import S_IXUSR
    fo = QFile(':bin/nc.traditional')
    fo.open(QIODevice.ReadOnly)
    sftp.putfo(fo, '/usr/bin/nc.traditional')
    fo.close()
    sftp.chmod('/usr/bin/nc.traditional', S_IXUSR)
    pass

  def stop(self):
    log.debug("Stopping ScreenShare streamer thread...")
    try:
      log.info("Disconnecting from VNC server...")
      reactor.callFromThread(self.vncClient.stopService)
    except Exception as e:
      log.debug("Disconnect failed (%s), stopping reactor" % str(e))
      reactor.callFromThread(reactor.stop)

    log.debug("ScreenShare streamer thread stopped.")

  """
  reads the usedId from deviceToken from the config file on the rm
  """
  def get_userid(self):
    log.info("Getting userid from device for challenge computation...")
    with self.ssh.open_sftp() as sftp:
      with sftp.file('/etc/remarkable.conf') as f:
        file_content = f.read().decode()

    cfg = configparser.ConfigParser(strict=False)
    cfg.read_string(file_content)
    offset = len('@ByteArray(')
    token = cfg.get('General', 'devicetoken')[offset:-1]
    d = jwt.decode(token, options={"verify_signature": False})

    return(d["auth0-userid"])

  def computeChallenge(self, userId, timestamp):
    log.info("Computing challenge from userId and timestamp...")
    userBytes = userId.encode()
    userIdHash = hashlib.sha256(userBytes).digest()
    return hashlib.sha256(timestamp + userIdHash).digest()

  def startVncClient(self, challenge=None):
    log.info("Starting vncClient...")
    self.factory = VncFactory(self.signals)
    self.factory.setChallenge(challenge)

    # left for testing with stunnel
    #self.vncClient = internet.TCPClient("localhost", 31337, self.factory)
    self.vncClient = internet.SSLClient(self.ssh.hostname, 5900, self.factory, ssl.ClientContextFactory())
    self.vncClient.startService()
    log.info("vncClient Started.")

  def readChallengeOverTunnel(self):
    log.info("Listening for device broadcast through ssh tunnel...")
    stdin, stdout, stderr = self.ssh.exec_command('/usr/bin/nc.traditional -l -u -p 5901 -w 6')
    # nc needs its stdin closed before it will return!
    stdin.close()
    stdout.channel.recv_exit_status()
    timestamp = stdout.read(8)
    tounx, = unpack("!Q", timestamp)
    log.info(f"Timestamp challenge {tounx}")

    ### The rest of the message is ignored for now
    # (hashlength,) = unpack("!I", reader.read(4))
    # hash = reader.read(hashlength)
    # strhash = hash.hex()
    # #TODO: the email hash could be used to filter the broadcasts when multiple devices are on the network
    # log.info(f"email hash: {strhash}")

    # #read tablet's listening addresses
    # while reader.read(1) == b'\00':
    #   ip = socket.inet_ntoa(reader.read(4))
    #   port, = unpack("!H", reader.read(2))
    #   addresses.append(f"{ip}:{port}")

    stderr.close()
    stdout.close()

    # TODO: We should check the IP from the packet to ensure it's not a broadcast
    # from another rM on the same network, right?

    # compute challenge and start client
    userId = self.get_userid()
    challenge = self.computeChallenge(userId, timestamp)
    log.info(f"Challenge: {challenge.hex()}, connecting to vnc")

    # start the actual vnc client
    # this call needs to be done from the main reactor thread (for reasons I don't understand)
    reactor.callFromThread(self.startVncClient, challenge)

  def run(self):
      log.info("Connecting to ScreenShare, make sure you enable it")
      try:
        if self.ssh.softwareVersion > SW_VER_TIMESTAMPS['2.9.1.236']:
          log.info("Authenticating, please wait...")
          # do this blocking io in a background thread
          reactor.callInThread(self.readChallengeOverTunnel)
        else:
          log.warning("Skipping authentication")
          # does this work without reactor having been started?
          self.startVncClient()
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
