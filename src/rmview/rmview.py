from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *

from . import resources
from .workers import FrameBufferWorker, PointerWorker
from .connection import rMConnect, RejectNewHostKey, AddNewHostKey, UnknownHostKeyException
from .viewer import QtImageViewer

from paramiko import BadHostKeyException, HostKeys

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

    self.CONFIG_DIR = QStandardPaths.standardLocations(QStandardPaths.ConfigLocation)[0]
    self.DEFAULT_CONFIG = os.path.join(self.CONFIG_DIR, 'rmview.json')
    self.LOCAL_KNOWN_HOSTS = os.path.join(self.CONFIG_DIR, 'rmview_known_hosts')

    config_files = [] if len(args) < 2 else [args[1]]
    config_files += ['rmview.json', self.DEFAULT_CONFIG]
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

    self.bar = QMenuBar()
    self.setWindowIcon(QIcon(':/assets/rmview.svg'))

    self.viewer = QtImageViewer()
    if 'background_color' in self.config:
      self.viewer.setBackgroundBrush(QBrush(QColor(self.config.get('background_color'))))
    act = QAction('Clone current frame', self)
    act.triggered.connect(self.cloneViewer)
    # self.viewer.menu.addSeparator()
    self.viewer.menu.addAction(act)

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

    # Setup global menu
    menu = self.bar.addMenu('&View')
    act = QAction('Rotate clockwise', self)
    act.setShortcut('Ctrl+Right')
    act.triggered.connect(self.viewer.rotateCW)
    menu.addAction(act)
    act = QAction('Rotate counter-clockwise', self)
    act.setShortcut('Ctrl+Left')
    act.triggered.connect(self.viewer.rotateCCW)
    menu.addAction(act)
    menu.addSeparator()
    act = QAction('Save screenshot', self)
    act.setShortcut('Ctrl+S')
    act.triggered.connect(self.viewer.screenshot)
    menu.addAction(act)
    menu.addSeparator()


    if not self.ensureConnConfig(): # I know, it's ugly
      QTimer.singleShot(0, lambda: self.quit())
      return

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
        return False

    auth_method = self.config['ssh'].get('auth_method')
    if (auth_method == 'password' and 'password' not in self.config['ssh']) or \
       (auth_method is None and 'password' not in self.config['ssh'] and 'key' not in self.config['ssh']):
      password, ok = QInputDialog.getText(self.viewer, "Configuration","reMarkable password:", QLineEdit.Password)
      if ok:
        self.config['ssh']['password'] = password or ""
      else:
        return False

    # backwards compatibility
    if self.config['ssh'].get('insecure_auto_add_host') and 'host_key_policy' not in self.config['ssh']:
      log.warning("The 'insecure_auto_add_host' setting is deprecated, see documentation.")
      self.config['ssh']['host_key_policy'] = "ignore_all"

    if self.config['ssh'].get('host_key_policy') == "auto_add":
      if not os.path.isfile(self.LOCAL_KNOWN_HOSTS):
        open(self.LOCAL_KNOWN_HOSTS, 'a').close()

    log.info(self.config)
    return True

  def requestConnect(self, host_key_policy=None):
    self.viewer.setWindowTitle("rMview - Connecting...")
    args = self.config.get('ssh')
    if host_key_policy:
      args = args.copy()
      args['host_key_policy'] = host_key_policy
    self.threadpool.start(
      rMConnect(**args,
                known_hosts=self.LOCAL_KNOWN_HOSTS,
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

    _,out,_ = ssh.exec_command("cat /sys/devices/soc0/machine")
    rmv = out.read().decode("utf-8")
    version = re.fullmatch(r"reMarkable (\d+)\..*\n", rmv)
    if version is None or version[1] not in ["1", "2"]:
      log.error("Device is unsupported: '%s' [%s]", rmv, version[1] if version else "unknown device")
      QMessageBox.critical(None, "Unsupported device", 'The detected device is %s.\nrmView currently only supports reMarkable 1.' % rmv)
      self.quit()
      return

    version = int(version[1])

    # check needed files are in place
    _,out,_ = ssh.exec_command("[ -x $HOME/rM-vnc-server-standalone ]")
    if out.channel.recv_exit_status() != 0:
      mbox = QMessageBox(QMessageBox.NoIcon, 'Missing components', 'Your reMarkable is missing some needed components.')
      icon = QPixmap(":/assets/problem.svg")
      icon.setDevicePixelRatio(self.devicePixelRatio())
      mbox.setIconPixmap(icon)
      mbox.setInformativeText(
        "To work properly, rmView needs the rM-vnc-server-standalone program "\
        "to be installed on your tablet.\n"\
        "You can install them manually, or let rmView do the work for you by pressing 'Auto Install' below.\n\n"\
        "If you are unsure, please consult the documentation.")
      mbox.addButton(QMessageBox.Cancel)
      mbox.addButton(QMessageBox.Help)
      mbox.addButton("Settings...", QMessageBox.ResetRole)
      mbox.addButton("Auto Install", QMessageBox.AcceptRole)
      mbox.setDefaultButton(0)
      answer = mbox.exec()
      log.info(answer)
      if answer == 1:
        log.info("Installing...")
        try:
          sftp = ssh.open_sftp()
          from stat import S_IXUSR
          fo = QFile(':bin/rM%d-vnc-server-standalone' % version)
          fo.open(QIODevice.ReadOnly)
          sftp.putfo(fo, 'rM-vnc-server-standalone')
          fo.close()
          sftp.chmod('rM-vnc-server-standalone', S_IXUSR)
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

    self.penworker = PointerWorker(ssh, path="/dev/input/event%d" % (version-1))
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

    confpath = os.path.abspath(self.config_file or self.DEFAULT_CONFIG)
    if not os.path.isfile(confpath):
      os.makedirs(os.path.dirname(confpath), exist_ok=True)
      with open(confpath, "w") as f:
        json.dump({
            "ssh": {"address": [self.config['ssh'].get('address', "10.11.99.1")]},
            "orientation": "auto",
            "pen_size": 15,
            "pen_color": "red",
            "pen_trail": 200
          }, f, indent=4)
    QDesktopServices.openUrl(QUrl("file:///" + confpath))
    self.quit()

  @pyqtSlot(Exception)
  def connectionError(self, e):
    self.viewer.setWindowTitle("rMview - Could not connect!")
    log.error(e)
    mbox = QMessageBox(QMessageBox.NoIcon, 'Connection error', "Connection attempt failed", parent=self.viewer)
    icon = QPixmap(":/assets/dead.svg")
    icon.setDevicePixelRatio(self.devicePixelRatio())
    mbox.setIconPixmap(icon)
    mbox.addButton("Settings...", QMessageBox.ResetRole)
    mbox.addButton(QMessageBox.Cancel)
    if isinstance(e, BadHostKeyException):
      mbox.setDetailedText(str(e))
      mbox.setInformativeText(
        "<big>The host at %s has the wrong key.<br>"
        "This usually happens just after a software update on the tablet.</big><br><br>"
        "You have three options to fix this permanently:"
        "<ol><li>"
        "Press Update to replace the old key with the new."
        "<br></li><li>"
        "Change your <code>~/.ssh/known_hosts</code> file to match the new fingerprint.<br>"
        "The easiest way to do this is connecting manually via ssh and follow the instructions."
        "<br></li><li>"
        "Set <code>\"host_key_policy\": \"ignore_new\"</code> in the <code>ssh</code> section of rmView\'s settings.<br>"
        "This is not recommended unless you are in a trusted network."
        "<br></li><ol>" % (e.hostname)
      )
      mbox.addButton("Ignore", QMessageBox.NoRole)
      mbox.addButton("Update", QMessageBox.YesRole)
    elif isinstance(e, UnknownHostKeyException):
      mbox.setDetailedText(str(e))
      mbox.setInformativeText(
        "<big>The host at %s is unknown.<br>"
        "This usually happens if this is the first time you use ssh with your tablet.</big><br><br>"
        "You have three options to fix this permanently:"
        "<ol><li>"
        "Press Add to add the key to the known hosts."
        "<br></li><li>"
        "Change your <code>~/.ssh/known_hosts</code> file to match the new fingerprint.<br>"
        "The easiest way to do this is connecting manually via ssh and follow the instructions."
        "<br></li><li>"
        "Set <code>\"host_key_policy\": \"ignore_new\"</code> in the <code>ssh</code> section of rmView\'s settings.<br>"
        "This is not recommended unless you are in a trusted network."
        "<br></li><ol>" % (e.hostname)
      )
      mbox.addButton("Ignore", QMessageBox.NoRole)
      mbox.addButton("Add", QMessageBox.YesRole)
    else:
      mbox.setInformativeText("I could not connect to the reMarkable at %s:\n%s." % (self.config.get('ssh').get('address'), e))
      mbox.addButton(QMessageBox.Retry)
      mbox.setDefaultButton(QMessageBox.Retry)
    answer = mbox.exec()
    if answer == QMessageBox.Retry:
      self.requestConnect()
    elif answer == QMessageBox.Cancel:
      self.quit()
    elif answer == 1: # Ignore
      self.requestConnect(host_key_policy="ignore_all")
    elif answer == 2: # Add/Update
      if not os.path.isfile(self.LOCAL_KNOWN_HOSTS):
        open(self.LOCAL_KNOWN_HOSTS, 'a').close()
      hk = HostKeys(self.LOCAL_KNOWN_HOSTS)
      hk.add(e.hostname, e.key.get_name(), e.key)
      hk.save(self.LOCAL_KNOWN_HOSTS)
      log.info("Saved host key in %s", self.LOCAL_KNOWN_HOSTS)
      self.requestConnect()
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
