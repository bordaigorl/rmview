# from PyQt5.QtGui import *
# from PyQt5.QtWidgets import *
from PyQt5.QtCore import *


import paramiko
import struct
import time

import sys
import os
import logging
log = logging.getLogger('rmview')



class rMConnectSignals(QObject):
  onConnect = pyqtSignal(object)
  onError = pyqtSignal(Exception)


class rMConnect(QRunnable):

  _exception = None

  def __init__(self, address='10.11.99.1', username='root', password=None, key=None, timeout=1, onConnect=None, onError=None):
    super(rMConnect, self).__init__()
    self.address = address
    self.signals = rMConnectSignals()
    if callable(onConnect):
      self.signals.onConnect.connect(onConnect)
    if callable(onError):
      self.signals.onError.connect(onError)
    # self.key = key
    try:
      self.client = paramiko.SSHClient()

      if key is not None:
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        key = os.path.expanduser(key)
        try:
          pkey = paramiko.RSAKey.from_private_key_file(key)
        except paramiko.ssh_exception.PasswordRequiredException:
          passphrase, ok = QInputDialog.getText(self.viewer, "Configuration","SSH key passphrase:", QLineEdit.Password)
          if ok:
            pkey = paramiko.RSAKey.from_private_key_file(key, password=passphrase)
          else:
            raise Exception("A passphrase for SSH key is required")
      else:
        pkey = None
        if password is None:
          raise Exception("Must provide either password or SSH key")

      self.options = {
        'username': username,
        'password': password,
        'pkey': pkey,
        'timeout': timeout,
        'look_for_keys': False
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
      self.signals.onConnect.emit(self.client)
    except Exception as e:
      log.error("Could not connect to %s: %s", self.options.get('address'), e)
      log.info("Please check your remarkable is connected and retry.")
      self.signals.onError.emit(e)
    log.debug('Stopping connection worker')


