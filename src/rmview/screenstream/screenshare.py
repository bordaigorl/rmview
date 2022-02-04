from PyQt6.QtGui import *
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *

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

# the screenshare vnc auth uses udp broadcasts
class ChallengeReaderProtocol(DatagramProtocol):
  clients = {}

  def __init__(self, callback):
    self.callback = callback

  def datagramReceived(self, datagram, host):
    reader = io.BytesIO(datagram)

    # the timestamp is needed for the challenge
    timestamp = reader.read(8)
    tounx, = unpack("!Q", timestamp)
    if timestamp in self.clients:
      log.debug(f"skipping challenge {tounx}")
      return
    log.info(f"received timestamp challenge {tounx}")

    if not self.callback(timestamp):
      log.debug("Stopping listening for timestamps")
      self.transport.stopListening()

    self.clients[timestamp] = addresses = []

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

    # log.info(addresses)



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
    userBytes = userId.encode()
    userIdHash = hashlib.sha256(userBytes).digest()
    return hashlib.sha256(timestamp + userIdHash).digest()

  #Hack to run the vnc with the challenge
  def runVnc(self, timestamp):
    if not self.factory:
      userId = self.get_userid()
      challenge = self.computeChallenge(userId, timestamp)
      log.info(f"Challenge: {challenge.hex()}, connecting to vnc")
      self.startVncClient(challenge)
    return False

  def startVncClient(self, challenge=None):
    self.factory = VncFactory(self.signals)
    self.factory.setChallenge(challenge)

    # left for testing with stunnel
    #self.vncClient = internet.TCPClient("localhost", 31337, self.factory)
    self.vncClient = internet.SSLClient(self.ssh.hostname, 5900, self.factory, ssl.ClientContextFactory())
    self.vncClient.startService()

  def run(self):
      log.info("Connecting to ScreenShare, make sure you enable it")
      try:
        if self.ssh.softwareVersion > SW_VER_TIMESTAMPS['2.9.1.236']:
          log.warning("Authenticating, please wait...")
          challengeReader = ChallengeReaderProtocol(self.runVnc)
          reactor.listenUDP(5901, challengeReader)
        else:
          log.warning("Skipping authentication")
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
