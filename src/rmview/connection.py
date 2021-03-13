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

  def __init__(self, address='10.11.99.1', username='root', password=None, key=None, timeout=3,
               onConnect=None, onError=None, host_key_policy=None, known_hosts=None, **kwargs):
    super(rMConnect, self).__init__()
    self.address = address
    self.signals = rMConnectSignals()
    if callable(onConnect):
      self.signals.onConnect.connect(onConnect)
    if callable(onError):
      self.signals.onError.connect(onError)

    try:
      self.client = paramiko.SSHClient()

      if host_key_policy != "ignore_all":
        if known_hosts and os.path.isfile(known_hosts):
          log.info("Using known hosts file: %s" % (known_hosts))
          self.client.load_host_keys(known_hosts)
          log.info("LOADED %s", known_hosts)
        else:
          log.info("Using system default known hosts file")
          # ideally we would want to always load the system ones
          # and have the local keys have precedence, but paramiko gives
          # always precedence to system keys
          # There is extremly slow in system with many known host entries... :/
          # See https://github.com/paramiko/paramiko/issues/191
          self.client.load_system_host_keys()

      policy = HOST_KEY_POLICY.get(host_key_policy, RejectNewHostKey)
      self.client.set_missing_host_key_policy(policy())

      if key is not None:
        key = os.path.expanduser(key)

        if password:
            # password protected key file, password provided in the config
            pkey = paramiko.RSAKey.from_private_key_file(key, password=password)
        else:
            try:
                pkey = paramiko.RSAKey.from_private_key_file(key)
            except paramiko.ssh_exception.PasswordRequiredException:
                passphrase, ok = QInputDialog.getText(None, "Configuration","SSH key passphrase:", QLineEdit.Password)
                if ok:
                    pkey = paramiko.RSAKey.from_private_key_file(key, password=passphrase)
                else:
                    raise Exception("A passphrase for SSH key is required")
      else:
        pkey = None
        if password is None:
          log.warning("No key nor password given. System-wide SSH connection parameters are going to be used.")

      self.options = {
        'username': username,
        'password': password,
        'pkey': pkey,
        'timeout': timeout,
      }
    except Exception as e:
      self._exception = e

  @pyqtSlot()
  def run(self):
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
    log.debug('Stopping connection worker')


