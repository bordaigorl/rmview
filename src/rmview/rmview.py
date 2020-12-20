from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *

from . import resources
from .workers import FrameBufferWorker, PointerWorker
from .connection import rMConnect
from .viewer import QtImageViewer

from paramiko import BadHostKeyException, SSHException

from .rmparams import *

import sys
import os
import json
import re

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
  trail = None  # None: disabled, False: inactive, True: active

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
        f = os.path.expanduser(f)
        with open(f) as config_file:
          self.config = json.load(config_file)
          self.config_file = f
          log.info("Fetching configuration from " + f)
          break
      except json.JSONDecodeError as e:
        log.error("Malformed configuration in %s: %s" % (f, e))
      except Exception as e:
        log.debug("Configuration failure in %s: %s" % (f, e))
    self.config.setdefault('ssh', {})
    self.pen_size = self.config.get('pen_size', self.pen_size)
    self.trailPen = QPen(QColor(self.config.get('pen_color', 'red')), max(1, self.pen_size // 3))
    self.trailPen.setCapStyle(Qt.RoundCap)
    self.trailPen.setJoinStyle(Qt.RoundJoin)
    self.trailDelay = self.config.get('pen_trail', 200)
    self.trail = None if self.trailDelay == 0 else False

    self.setWindowIcon(QIcon(':/assets/rmview.svg'))

    self.viewer = QtImageViewer()
    if 'bg_color' in self.config:
      self.viewer.setBackgroundBrush(QBrush(QColor(self.config.get('background_color'))))
    act = QAction('Clone current frame', self)
    act.triggered.connect(self.cloneViewer)
    # self.viewer.menu.addSeparator()
    self.viewer.menu.addAction(act)
    if self.config_file:
      act = QAction('Settings...', self)
      act.triggered.connect(self.openSettings)
      self.viewer.menu.addSeparator()
      self.viewer.menu.addAction(act)

    self.viewer.setWindowTitle("rMview")
    self.viewer.show()

    self.orient = None
    orient = self.config.get('orientation', 'landscape')
    if orient == 'landscape':
      self.viewer.rotateCW()
      self.autoResize(WIDTH / HEIGHT)
    elif orient == 'portrait':
      self.autoResize(HEIGHT / WIDTH)
    else: # orient
      self.autoResize(HEIGHT / WIDTH)
      self.orient = True

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
    self.aboutToQuit.connect(self.joinWorkers)
    self.requestConnect()

  def detectOrientation(self, image):
    c = image.pixel
    portrait = False
    # print(c(48, 47) , c(72, 72) , c(55, 55) , c(64, 65))
    if c(48, 47) == 4278190080 and  c(72, 72) == 4278190080 and \
       (c(55, 55) == 4294967295 or c(64, 65) == 4294967295):
       if c(61, 1812) != 4278190080 or c(5,5) == 4278190080:
         portrait = True
    elif c(1356, 47) == 4278190080 and c(1329, 72) == 4278190080 and \
       (c(1348, 54) == 4294967295 or c(1336, 65) == 4294967295):
      portrait = True
    elif c(5,5) == 4278190080:
      portrait = True
    elif c(40,47) == 4278190080 and c(40,119) == 4278190080:
      portrait = True
    if portrait:
       self.viewer.portrait()
       self.autoResize(HEIGHT / WIDTH)
    else:
       self.viewer.landscape()
       self.autoResize(WIDTH / HEIGHT)

  def autoResize(self, ratio):
    dg = self.desktop().availableGeometry(self.viewer)
    ds = dg.size() * 0.7
    if ds.width() * ratio > ds.height():
      ds.setWidth(int(ds.height() / ratio))
    else:
      ds.setHeight(int(ds.width() * ratio))
    self.viewer.resize(ds)
    fg = self.viewer.frameGeometry()
    fg.moveCenter(dg.center())
    self.viewer.move(fg.topLeft())

  def ensureConnConfig(self):
    address = self.config['ssh'].get('address', ["10.11.99.1"])
    if type(address) is list:
      address, ok = QInputDialog.getItem(self.viewer, "Connection", "Address:", address)
      if ok and address:
        self.config['ssh']['address'] = address
      else:
        self.quit()

    if self.config['ssh'].get('ask_password'):
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

    # check we are dealing with RM1
    # cat /sys/devices/soc0/machine -> reMarkable 1.x
    _,out,_ = ssh.exec_command("cat /sys/devices/soc0/machine")
    rmv = out.read().decode("utf-8")
    ver = re.fullmatch(r"reMarkable (\d+)\..*\n", rmv)
    if ver is None or ver[1] != "1":
      log.error("Device is unsupported: '%s' [%s]", rmv, ver[1] if ver else "unknown device")
      QMessageBox.critical(None, "Unsupported device", 'The detected device is %s.\nrmView currently only supports reMarkable 1.' % rmv)
      self.quit()
      return

    # check needed files are in place
    _,out,_ = ssh.exec_command("[ -x $HOME/rM-vnc-server ] && [ -e $HOME/mxc_epdc_fb_damage.ko ]")
    if out.channel.recv_exit_status() != 0:
      mbox = QMessageBox(QMessageBox.NoIcon, 'Missing components', 'Your reMarkable is missing some needed components.')
      icon = QPixmap(":/assets/problem.svg")
      icon.setDevicePixelRatio(self.devicePixelRatio())
      mbox.setIconPixmap(icon)
      mbox.setInformativeText(
        "To work properly, rmView needs the rM-vnc-server and mxc_epdc_fb_damage.ko files "\
        "to be installed on your tablet.\n"\
        "You can install them manually, or let rmView do the work for you by pressing 'Auto Install' below.\n\n"\
        "If you are unsure, please consult the documentation.")
      mbox.addButton(QMessageBox.Cancel)
      mbox.addButton(QMessageBox.Help)
      if self.config_file:
        mbox.addButton("Settings...", QMessageBox.YesRole)
      mbox.addButton("Auto Install", QMessageBox.AcceptRole)
      mbox.setDefaultButton(0)
      answer = mbox.exec()
      log.info(answer)
      if answer == 1:
        log.info("Installing...")
        try:
          sftp = ssh.open_sftp()
          from stat import S_IXUSR
          fo = QFile(':bin/rM-vnc-server')
          fo.open(QIODevice.ReadOnly)
          sftp.putfo(fo, 'rM-vnc-server')
          fo.close()
          sftp.chmod('rM-vnc-server', S_IXUSR)
          fo = QFile(':bin/mxc_epdc_fb_damage.ko')
          fo.open(QIODevice.ReadOnly)
          sftp.putfo(fo, 'mxc_epdc_fb_damage.ko')
          fo.close()
          log.info("Installation successful!")
        except Exception as e:
          log.error('%s %s', type(e), e)
          QMessageBox.critical(None, "Error", 'There has been an error while trying to install the required components on the tablet.\n%s\n.' % e)
          self.quit()
          return
      elif answer == QMessageBox.Cancel:
        self.quit()
        return
      elif answer == QMessageBox.Help:
        QDesktopServices.openUrl(QUrl("https://github.com/bordaigorl/rmview"))
        self.quit()
        return
      else:
        self.openSettings(prompt=False)
        return

    self.fbworker = FrameBufferWorker(ssh, delay=self.config.get('fetch_frame_delay'))
    self.fbworker.signals.onNewFrame.connect(self.onNewFrame)
    self.fbworker.signals.onFatalError.connect(self.frameError)
    self.threadpool.start(self.fbworker)

    self.penworker = PointerWorker(ssh)
    self.threadpool.start(self.penworker)
    self.pen = self.viewer.scene.addEllipse(0,0,self.pen_size,self.pen_size,
                                            pen=QPen(QColor('white')),
                                            brush=QBrush(QColor(self.config.get('pen_color', 'red'))))
    self.pen.hide()
    self.pen.setZValue(100)
    self.penworker.signals.onPenMove.connect(self.movePen)
    if self.config.get("show_pen_on_lift", True):
      self.penworker.signals.onPenLift.connect(self.showPen)
    if self.config.get("hide_pen_on_press", True):
        self.penworker.signals.onPenPress.connect(self.hidePen)
    self.penworker.signals.onPenNear.connect(self.showPen)
    self.penworker.signals.onPenFar.connect(self.hidePen)


  @pyqtSlot(QImage)
  def onNewFrame(self, image):
    if self.orient:
      self.detectOrientation(image)
      self.orient = False
    self.viewer.setImage(image)

  @pyqtSlot()
  def hidePen(self):
    if self.trail is not None:
      self.trail = False
    self.pen.hide()

  @pyqtSlot()
  def showPen(self):
    if self.trail is not None:
      self.trail = False
    self.pen.show()

  @pyqtSlot(int, int)
  def movePen(self, x, y):
    y = 20951 - y
    ratio_width, ratio_height = WIDTH / 15725, HEIGHT / 20951
    scaling = ratio_width if ratio_width > ratio_height else ratio_height
    x = scaling * (x - (15725 - WIDTH / scaling) / 2)
    y = scaling * (y - (20951 - HEIGHT / scaling) / 2)
    if self.trail is not None:
      if self.trail is False:
        self.trail = True
      elif self.pen.isVisible():
        old = self.pen.rect().center()
        t = self.viewer.scene.addLine(x,y,old.x(),old.y(),self.trailPen)
        QTimer.singleShot(self.trailDelay // 2, lambda: t.setOpacity(.5))
        QTimer.singleShot(self.trailDelay, lambda: self.viewer.scene.removeItem(t))
    self.pen.setRect(x - (self.pen_size // 2), y - (self.pen_size // 2), self.pen_size, self.pen_size)

  @pyqtSlot()
  def cloneViewer(self):
    img = self.viewer.image()
    v = QtImageViewer()
    v.setImage(img)
    v.show()

  @pyqtSlot()
  def openSettings(self, prompt=True):
    if prompt:
      ans = QMessageBox.information(
              self.viewer,
              "Opening Settings",
              'To load the new settings you need to relaunch rMview.',
              buttons=(QMessageBox.Ok | QMessageBox.Cancel),
              defaultButton=QMessageBox.Ok
            )
      if ans == QMessageBox.Cancel:
        return

    QDesktopServices.openUrl(QUrl("file://" + os.path.abspath(self.config_file)))
    self.quit()

  @pyqtSlot(Exception)
  def connectionError(self, e):
    self.viewer.setWindowTitle("rMview - Could not connect!")
    log.error(e)
    mbox = QMessageBox(QMessageBox.NoIcon, 'Connection error', "Connection attempt failed", parent=self.viewer)
    icon = QPixmap(":/assets/dead.svg")
    icon.setDevicePixelRatio(self.devicePixelRatio())
    mbox.setIconPixmap(icon)
    if isinstance(e, BadHostKeyException):
      mbox.setDetailedText(str(e))
      mbox.setInformativeText(
        "<big>The host at %s has the wrong key.<br>"
        "This usually happens just after a software update on the tablet.</big><br><br>"
        "You have three options to fix this problem:"
        "<ol><li>"
        "Change your <code>~/.ssh/known_hosts</code> file to match the new fingerprint.<br>"
        "The easiest way to do this is connecting manually via ssh and follow the instructions."
        "<br></li><li>"
        "Set <code>\"insecure_auto_add_host\": true</code> to rmView\'s settings.<br>"
        "This is not recommended unless you are in a trusted network."
        "<br></li><li>"
        "Connect using username/password."
        "<br></li><ol>" % (self.config.get('ssh').get('address'))
      )
    elif isinstance(e, SSHException) and str(e).endswith('known_hosts'):
      mbox.setInformativeText(
        "<big>The host at %s is unknown.<br>"
        "This usually happens if this is the first time you use ssh with your tablet.</big><br><br>"
        "You have three options to fix this problem:"
        "<ol><li>"
        "Change your <code>~/.ssh/known_hosts</code> file to match the new fingerprint.<br>"
        "The easiest way to do this is connecting manually via ssh and follow the instructions."
        "<br></li><li>"
        "Set <code>\"insecure_auto_add_host\": true</code> to rmView\'s settings.<br>"
        "This is not recommended unless you are in a trusted network."
        "<br></li><li>"
        "Connect using username/password."
        "<br></li><ol>" % (self.config.get('ssh').get('address'))
      )
    else:
      mbox.setInformativeText("I could not connect to the reMarkable at %s:\n%s." % (self.config.get('ssh').get('address'), e))
    mbox.addButton(QMessageBox.Cancel)
    if self.config_file:
      mbox.addButton("Settings...", QMessageBox.ResetRole)
    mbox.addButton(QMessageBox.Retry)
    mbox.setDefaultButton(QMessageBox.Retry)
    answer = mbox.exec()
    if answer == QMessageBox.Retry:
      self.requestConnect()
    elif answer == QMessageBox.Cancel:
      self.quit()
    else:
      self.openSettings(prompt=False)
      self.quit()

  @pyqtSlot(Exception)
  def frameError(self, e):
    QMessageBox.critical(self.viewer, "Error", 'Please check your reMarkable is properly configured, see the documentation for instructions.\n\n%s' % e)
    self.quit()

def rmViewMain():
  log.setLevel(logging.INFO)
  QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
  ecode = rMViewApp(sys.argv).exec_()
  print('\nBye!')
  sys.exit(ecode)

if __name__ == '__main__':
  rmViewMain()
