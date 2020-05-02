from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *

import resources
from workers import FrameBufferWorker, PointerWorker
from connection import rMConnect
from viewer import QtImageViewer

from rmparams import *

import sys
import os
import json

import logging
logging.basicConfig(format='%(message)s')
log = logging.getLogger('rmview')


class rMViewApp(QApplication):

  config_file = None
  config = {}

  viewer = None
  fbworker = None
  penworker = None
  ssh = None

  pen = None
  pen_size = 15

  def __init__(self, args):
    super(rMViewApp, self).__init__(args)
    config_files = [] if len(args) < 2 else [args[1]]
    config_files += ['rmview.json']
    rmview_conf = os.environ.get("RMVIEW_CONF") 
    if rmview_conf is not None:
        config_files += [rmview_conf]
    log.info("Searching configuration in " + ', '.join(config_files))
    for f in config_files:
      try:
        with open(os.path.expanduser(f)) as config_file:
          self.config = json.load(config_file)
          self.config_file = config_file
          log.info("Fetching configuration from " + f)
          break
      except Exception as e:
          log.debug("Configuration failure in %s: %s" % (f, e))
          pass
    self.config.setdefault('ssh', {})
    self.pen_size = self.config.get('pen_size', self.pen_size)


    self.setWindowIcon(QIcon(':/assets/rmview.svg'))

    self.viewer = QtImageViewer()
    self.viewer.setWindowTitle("rMview")
    self.viewer.resize(QDesktopWidget().availableGeometry(self.viewer).size() * 0.7);
    if self.config.get('orientation', 'landscape') == 'landscape':
      self.viewer.rotateCW()
    self.viewer.show()

    # bar = QMenuBar()
    # menu = bar.addMenu('&View')
    # act = QAction('Rotate clockwise', self)
    # act.setShortcut('Ctrl+Right')
    # act.triggered.connect(self.viewer.rotateCW)
    # menu.addAction(act)
    # act = QAction('Rotate counter-clockwise', self)
    # act.setShortcut('Ctrl+Left')
    # act.triggered.connect(self.viewer.rotateCCW)
    # menu.addAction(act)
    # menu.addSeparator()
    # act = QAction('Save screenshot', self)
    # act.setShortcut('Ctrl+S')
    # act.triggered.connect(self.viewer.screenshot)


    self.ensureConnConfig()

    self.threadpool = QThreadPool()
    self.requestConnect()

    self.aboutToQuit.connect(self.joinWorkers)

    ecode = self.exec_()
    print('\nBye!')
    sys.exit(ecode)

  def ensureConnConfig(self):
    if self.config['ssh'].get('address') is None:
      address, ok = QInputDialog.getText(self.viewer, "Configuration","IP Address of your reMarkable:", QLineEdit.Normal, "10.11.99.1")
      if ok and address:
        self.config['ssh']['address'] = address
      else:
        self.quit()

    if self.config['ssh'].get('password') is None and self.config['ssh'].get('key') is None:
      password, ok = QInputDialog.getText(self.viewer, "Configuration","reMarkable password:", QLineEdit.Password)
      if ok:
        self.config['ssh']['password'] = password or ""
      else:
        self.quit()
    log.info(self.config)

  def requestConnect(self):
    self.viewer.setWindowTitle("rMview - Connecting...")
    self.threadpool.start(
      rMConnect(**self.config.get('ssh'),
                onError=self.connectionError,
                onConnect=self.connected ) )

  @pyqtSlot()
  def joinWorkers(self):
    if self.penworker is not None:
      self.penworker.stop()
    if self.fbworker is not None:
      self.fbworker.stop()
    if self.ssh is not None:
      self.ssh.close()
    self.threadpool.waitForDone()

  @pyqtSlot(object)
  def connected(self, ssh):
    self.ssh = ssh
    self.viewer.setWindowTitle("rMview - " + self.config.get('ssh').get('address'))
    self.fbworker = FrameBufferWorker(ssh, delay=self.config.get('fetch_frame_delay'))
    self.fbworker.signals.onNewFrame.connect(lambda image: self.viewer.setImage(image))
    self.fbworker.signals.onFatalError.connect(self.frameError)
    self.threadpool.start(self.fbworker)

    self.penworker = PointerWorker(ssh)
    self.threadpool.start(self.penworker)
    self.pen = self.viewer.scene.addEllipse(0,0,self.pen_size,self.pen_size,
                                            pen=QPen(QColorConstants.White),
                                            brush=QBrush(QColor(self.config.get('pen_color', 'red'))))
    self.pen.hide()
    self.pen.setZValue(100)
    self.penworker.signals.onPenMove.connect(self.movePen)
    self.penworker.signals.onPenLift.connect(self.pen.show)
    self.penworker.signals.onPenPress.connect(self.pen.hide)


  @pyqtSlot(int, int)
  def movePen(self, x, y):
      y = 20951 - y
      ratio_width, ratio_height = WIDTH / 15725, HEIGHT / 20951
      scaling = ratio_width if ratio_width > ratio_height else ratio_height
      x = scaling * (x - (15725 - WIDTH / scaling) / 2)
      y = scaling * (y - (20951 - HEIGHT / scaling) / 2)
      self.pen.setRect(x,y,self.pen_size,self.pen_size)


  @pyqtSlot(Exception)
  def connectionError(self, e):
    self.viewer.setWindowTitle("rMview - Could not connect!")
    log.error(e)
    mbox = QMessageBox(QMessageBox.NoIcon, 'Connection error', "Connection attempt failed", parent=self.viewer)
    icon = QPixmap(":/assets/dead.svg")
    icon.setDevicePixelRatio(self.devicePixelRatio())
    mbox.setIconPixmap(icon)
    mbox.setInformativeText("I could not connect to the reMarkable at %s:\n%s." % (self.config.get('ssh').get('address'), e))
    mbox.addButton(QMessageBox.Cancel)
    # mbox.addButton("Settings...", QMessageBox.ResetRole)
    mbox.addButton(QMessageBox.Retry)
    mbox.setDefaultButton(QMessageBox.Retry)
    answer = mbox.exec()
    if answer == QMessageBox.Retry:
      self.requestConnect()
    elif answer == QMessageBox.Cancel:
      self.quit()
    else:
      # self.open_settings()
      self.quit()

  @pyqtSlot(Exception)
  def frameError(self, e):
    QMessageBox.critical(self.viewer, "Error", 'Please check your reMarkable is properly configured and with LZ4 installed.\n\n%s' % e)
    self.quit()

if __name__ == '__main__':
  log.setLevel(logging.INFO)
  QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
  rMViewApp(sys.argv)
