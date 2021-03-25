# from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *


import paramiko
import struct
import time
from binascii import hexlify

import sys
import os
import logging
log = logging.getLogger('rmview')


class UnknownHostKeyException(paramiko.SSHException):

  def __init__(self, hostname, key):
    paramiko.SSHException.__init__(self, hostname, key)
    self.hostname = hostname
    self.key = key

  def __str__(self):
    msg = "Unknown host key for server '{}': got '{}'"
    return msg.format(
        self.hostname,
        self.key.get_base64(),
    )

AddNewHostKey = paramiko.AutoAddPolicy


class RejectNewHostKey(paramiko.MissingHostKeyPolicy):

  def missing_host_key(self, client, hostname, key):
    raise UnknownHostKeyException(hostname, key)


class IgnoreNewHostKey(paramiko.MissingHostKeyPolicy):

  def missing_host_key(self, client, hostname, key):
    log.warning("Unknown %s host key for %s: %s", key.get_name(), hostname, hexlify(key.get_fingerprint()))


HOST_KEY_POLICY = {
  "ask": RejectNewHostKey,
  "ignore_new": IgnoreNewHostKey,
  "ignore_all": IgnoreNewHostKey,
  "auto_add": AddNewHostKey
}



class rMConnectSignals(QObject):
  onConnect = pyqtSignal(object)
  onError = pyqtSignal(Exception)


class rMConnect(QRunnable):

  _exception = None
  _known_hosts = None

  def __init__(self, address='10.11.99.1', username='root', password=None, key=None, timeout=3,
               onConnect=None, onError=None, host_key_policy=None, known_hosts=None, **kwargs):
    super(rMConnect, self).__init__()

    self.address = address
    self.username = username
    self.password = password
    self.key = key
    self.timeout = timeout
    self.host_key_policy = host_key_policy
    self.known_hosts = known_hosts

    self.signals = rMConnectSignals()

    self.client = None
    self._exception = None

    if callable(onConnect):
      self.signals.onConnect.connect(onConnect)
    if callable(onError):
      self.signals.onError.connect(onError)

  def _initialize(self):
    # NOTE: Loading system known hosts can take a long time that's why it should happen inside
    # run() so it doesn't block the main qt render loop which will cause main QT window to freeze
    # until the loading completes.
    try:
      self.client = paramiko.SSHClient()

      if self.host_key_policy != "ignore_all":
        if self.known_hosts and os.path.isfile(self.known_hosts):
          log.info("Using known hosts file: %s" % (self.known_hosts))
          self.client.load_host_keys(self.known_hosts)
          log.info("Loaded known hosts from %s", self.known_hosts)
        else:
          log.info("Using system default known hosts file")
          log.info("Loading system default known hosts file, this may take a while...")
          # ideally we would want to always load the system ones
          # and have the local keys have precedence, but paramiko gives
          # always precedence to system keys
          # There is extremly slow in system with many known host entries... :/
          # See https://github.com/paramiko/paramiko/issues/191
          self.client.load_system_host_keys()
          log.info("System default known host file loaded")

      policy = HOST_KEY_POLICY.get(self.host_key_policy, RejectNewHostKey)
      self.client.set_missing_host_key_policy(policy())

      if self.key is not None:
        key = os.path.expanduser(self.key)

        if self.password:
            # password protected key file, password provided in the config
            pkey = paramiko.RSAKey.from_private_key_file(key, password=self.password)
        else:
            try:
                pkey = paramiko.RSAKey.from_private_key_file(key)
            except paramiko.ssh_exception.PasswordRequiredException:
                passphrase, ok = QInputDialog.getText(None, "Configuration","SSH key passphrase:",
                                                      QLineEdit.Password)
                if ok:
                    pkey = paramiko.RSAKey.from_private_key_file(key, password=passphrase)
                else:
                    raise Exception("A passphrase for SSH key is required")
      else:
        pkey = None
        if self.password is None:
          log.warning("No key nor password given. System-wide SSH connection parameters are going to be used.")

      self.options = {
        'username': self.username,
        'password': self.password,
        'pkey': pkey,
        'timeout': self.timeout,
      }
    except Exception as e:
      self._exception = e

  @pyqtSlot()
  def run(self):
    self._initialize()

    if self._exception is not None:
      self.signals.onError.emit(self._exception)
      log.debug('Aborting connection: %s', self._exception)
      return
    try:
      log.info('Connecting...') # pkey=key,
      self.client.connect(self.address, **self.options)
      log.info("Connected to {}".format(self.address))
      self.client.hostname = self.address
      self.signals.onConnect.emit(self.client)
    except Exception as e:
      log.error("Could not connect to %s: %s", self.address, e)
      log.info("Please check your remarkable is connected and retry.")
      self.signals.onError.emit(e)
    try:
      if self._known_hosts:
        self.client.save_host_keys(self._known_hosts)
    except Exception as e:
      log.warning("Could not save known keys at '%s'" % self._known_hosts)
    log.debug('Stopping connection worker')


