# from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *

from .rmparams import timestamp_to_version


import paramiko
import struct
import time
import re
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
               onConnect=None, onError=None, host_key_policy=None, known_hosts=None, auth_method=None, **kwargs):
    super(rMConnect, self).__init__()

    self.address = address
    self.username = username
    self.password = password
    self.timeout = timeout
    self.auth_method = auth_method
    self.host_key_policy = host_key_policy
    self._known_hosts = known_hosts

    if key is not None:
      key = os.path.expanduser(key)

      if password:
        # password protected key file, password provided in the config
        self.pkey = paramiko.RSAKey.from_private_key_file(key, password=password)
      else:
        try:
          self.pkey = paramiko.RSAKey.from_private_key_file(key)
        except paramiko.ssh_exception.PasswordRequiredException as exc:
          passphrase, ok = QInputDialog.getText(None, "Configuration","SSH key passphrase:",
                                                QLineEdit.Password)
          if ok:
            self.pkey = paramiko.RSAKey.from_private_key_file(key, password=passphrase)
          else:
            raise Exception("A passphrase for SSH key is required") from exc
    else:
      self.pkey = None
      if self.password is None:
        log.warning("No key nor password given. System-wide SSH connection parameters are going to be used.")


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
        if self._known_hosts and os.path.isfile(self._known_hosts):
          log.info("Using known hosts file: %s" % (self._known_hosts))
          self.client.load_host_keys(self._known_hosts)
          log.info("Loaded known hosts from %s", self._known_hosts)
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

      self.options = {
        'username': self.username,
        'password': self.password,
        'pkey': self.pkey,
        'timeout': self.timeout,
        # remarkable's Dropbear version (Dropbear v2019.78) does not support the server-sig-algs extension,
        # and also does not support sha2, so connection fails if sha2 is used
        # paramiko starting with version 2.9.0, paramiko defaults to sha2 if not explicitly disabled: https://github.com/paramiko/paramiko/issues/1961
        'disabled_algorithms': {'pubkeys': ['rsa-sha2-512', 'rsa-sha2-256']},
      }

      if self.auth_method == 'password':
        self.options['look_for_keys'] = False
        self.options['allow_agent'] = False

    except Exception as e:
      self._exception = e

  def _getVersion(self):
    _, out, _ = self.client.exec_command("cat /sys/devices/soc0/machine")
    rmv = out.read().decode("utf-8")
    version = re.fullmatch(r"reMarkable(?: Prototype)? (\d+)(\.\d+)*\n", rmv)
    if version is not None:
      version = int(version[1])
    return version, rmv.strip()

  def _getSwVersion(self):
    _, out, _ = self.client.exec_command("cat /etc/version")
    version_ts = int(out.read().decode("utf-8"))
    version = timestamp_to_version(version_ts)

    try:
      _, out, err = self.client.exec_command(r"grep 'REMARKABLE_RELEASE_VERSION=' /usr/share/remarkable/update.conf "
                                             r"| sed -r 's/(REMARKABLE_RELEASE_VERSION=)([0-9a-zA-Z.]+)/\2/'")
      config_version = tuple(int(v) for v in out.read().decode("utf-8").strip().split('.'))
      if (len(config_version) < 4): config_version += (0,)*(len(config_version) - 4);
      version = config_version
      log.debug("Using update.conf as SW version authority")
    except Exception as e:
      log.debug("Using /etc/version as SW version authority")

    return version


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
      self.client.deviceVersion, self.client.fullDeviceVersion = self._getVersion()
      self.client.softwareVersion = self._getSwVersion()
      log.info("Detected SW version: {}".format('.'.join(str(v) for v in self.client.softwareVersion)))
      self.signals.onConnect.emit(self.client)
    except Exception as e:
      log.error("Could not connect to %s: %s", self.address, e)
      log.info("Please check your remarkable is connected and retry.")
      self.signals.onError.emit(e)
    try:
      if self._known_hosts and os.path.isfile(self._known_hosts):
        self.client.save_host_keys(self._known_hosts)
    except Exception as e:
      log.warning("Could not save known keys at '%s'" % self._known_hosts)
    log.debug('Stopping connection worker')


