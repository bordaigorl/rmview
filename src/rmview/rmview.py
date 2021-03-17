from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *

from . import resources
from .workers import FrameBufferWorker, PointerWorker, KEY_Left, KEY_Right, KEY_Escape
from .connection import rMConnect, RejectNewHostKey, AddNewHostKey, UnknownHostKeyException
from .viewer import QtImageViewer

from paramiko import BadHostKeyException, HostKeys

from .rmparams import *

import sys
import os
import stat
import json
import re
import copy
import signal
import time

import logging
logging.basicConfig(format='%(asctime)s %(levelname)s [-] %(message)s')
log = logging.getLogger('rmview')


class rMViewApp(QApplication):

  config_file = None
  config = {}

  viewer = None
  fbworker = None
  penworker = None
  ssh = None

  streaming = True
  right_mode = True

  pen = None
  pen_size = 15
  trail = None  # None: disabled, False: inactive, True: active

  def __init__(self, args):
    super(rMViewApp, self).__init__(args)

    self.CONFIG_DIR = QStandardPaths.standardLocations(QStandardPaths.ConfigLocation)[0]
    self.DEFAULT_CONFIG = os.path.join(self.CONFIG_DIR, 'rmview.json')
    self.LOCAL_KNOWN_HOSTS = os.path.join(self.CONFIG_DIR, 'rmview_known_hosts')

    config_files = [] if len(args) < 2 else [args[1]]
    config_files += ['rmview.json']
    rmview_conf = os.environ.get("RMVIEW_CONF")
    if rmview_conf is not None:
        config_files += [rmview_conf]
    config_files += [self.DEFAULT_CONFIG]
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

    self._checkConfigFilePermissions(self.config_file)

    self.config.setdefault('ssh', {})
    self.pen_size = self.config.get('pen_size', self.pen_size)
    self.trailPen = QPen(QColor(self.config.get('pen_color', 'red')), max(1, self.pen_size // 3))
    self.trailPen.setCapStyle(Qt.RoundCap)
    self.trailPen.setJoinStyle(Qt.RoundJoin)
    self.trailDelay = self.config.get('pen_trail', 200)
    self.trail = None if self.trailDelay == 0 else False
    self.right_mode = self.config.get('right_mode', True)

    self.bar = QMenuBar()
    self.setWindowIcon(QIcon(':/assets/rmview.svg'))

    self.viewer = QtImageViewer()

    if 'background_color' in self.config:
      self.viewer.setBackgroundBrush(QBrush(QColor(self.config.get('background_color'))))

    ### ACTIONS
    self.cloneAction = QAction('Clone current frame', self.viewer)
    self.cloneAction.setShortcut(QKeySequence.New)
    self.cloneAction.triggered.connect(self.cloneViewer)
    self.viewer.addAction(self.cloneAction)
    ###
    self.pauseAction = QAction('Pause Streaming', self.viewer)
    self.pauseAction.setShortcut('Ctrl+P')
    self.pauseAction.triggered.connect(self.toggleStreaming)
    self.viewer.addAction(self.pauseAction)
    ###
    self.settingsAction = QAction('Settings...', self.viewer)
    self.settingsAction.triggered.connect(self.openSettings)
    self.viewer.addAction(self.settingsAction)
    ###
    self.quitAction = QAction('Quit', self.viewer)
    self.quitAction.setShortcut('Ctrl+Q')
    self.quitAction.triggered.connect(self.quit)
    self.viewer.addAction(self.quitAction)
    ###
    self.leftAction = QAction('Emulate Left Button', self)
    self.leftAction.setShortcut('Ctrl+Left')
    self.leftAction.triggered.connect(lambda: self.fbworker.keyEvent(KEY_Left))
    self.viewer.addAction(self.leftAction)
    ###
    self.rightAction = QAction('Emulate Right Button', self)
    self.rightAction.setShortcut('Ctrl+Right')
    self.rightAction.triggered.connect(lambda: self.fbworker.keyEvent(KEY_Right))
    self.viewer.addAction(self.rightAction)
    ###
    self.homeAction = QAction('Emulate Central Button', self)
    self.homeAction.setShortcut(QKeySequence.Cancel)
    self.homeAction.triggered.connect(lambda: self.fbworker.keyEvent(KEY_Escape))
    self.viewer.addAction(self.homeAction)


    ### VIEWER MENU ADDITIONS
    self.viewer.menu.addAction(self.cloneAction)
    self.viewer.menu.addAction(self.pauseAction)
    # inputMenu = self.viewer.menu.addMenu("Input")
    # inputMenu.addAction(self.leftAction)
    # inputMenu.addAction(self.rightAction)
    # inputMenu.addAction(self.homeAction)
    self.viewer.menu.addSeparator() # --------------------------
    self.viewer.menu.addAction(self.settingsAction)
    self.viewer.menu.addSeparator() # --------------------------
    self.viewer.menu.addAction(self.quitAction)

    self.viewer.setWindowTitle("rMview")
    self.viewer.show()

    # Display connecting image until we successfuly connect
    self.viewer.setImage(QPixmap(':/assets/connecting.png'))

    self.orient = 0
    orient = self.config.get('orientation', 'landscape')
    if orient == 'landscape':
      self.viewer.rotateCW()
      self.autoResize(WIDTH / HEIGHT)
    elif orient == 'portrait':
      self.autoResize(HEIGHT / WIDTH)
    else: # auto
      self.autoResize(HEIGHT / WIDTH)
      self.orient = 1 if orient == "auto_on_load" else 2

    # # Setup global menu
    # menu = self.bar.addMenu('&View')
    # menu.addAction(self.viewer.rotCWAction)
    # menu.addAction(self.viewer.rotCCWAction)
    # menu.addSeparator()
    # menu.addAction(self.viewer.screenshotAction)
    # menu.addSeparator()
    # menu.addAction(self.pauseAction)
    # menu.addAction(self.leftAction)
    # menu.addAction(self.rightAction)
    # menu.addAction(self.homeAction)


    if not self.ensureConnConfig(): # I know, it's ugly
      QTimer.singleShot(0, lambda: self.quit())
      return

    self.threadpool = QThreadPool()
    self.aboutToQuit.connect(self.joinWorkers)
    self.requestConnect()

  def detectOrientation(self, image):
    (tl,bl,tr) = find_circle_buttons(image)
    if tl is None and bl is None and tr is None:
      portrait = True # We are in the main screen/settings
    elif bl is None:
      portrait = self.right_mode
    else:
      portrait = False

    if portrait:
      if not self.viewer.is_portrait():
        self.viewer.portrait()
        self.autoResize(HEIGHT / WIDTH)
    elif not self.viewer.is_landscape():
        self.viewer.landscape()
        self.autoResize(WIDTH / HEIGHT)

  def autoResize(self, ratio):
    if self.viewer.windowState() & (QWindow.FullScreen | QWindow.Maximized):
      return
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

    config_sanitized = copy.deepcopy(self.config)
    if "password" in self.config.get("ssh", {}):
        config_sanitized["ssh"]["password"] = config_sanitized["ssh"]["password"][:3] + "*****"

    log.info("Config values: %s" % (str(config_sanitized)))
    return True

  def _checkConfigFilePermissions(self, file_path):
    """
    Emit a warning message if config file is readable by others.
    """
    st_mode = os.stat(file_path).st_mode

    if bool(st_mode & stat.S_IROTH) or bool(st_mode & stat.S_IWOTH):
      file_permissions = str(oct(st_mode)[4:])

      if file_permissions.startswith("0") and len(file_permissions) == 4:
          file_permissions = file_permissions[1:]

      log .warn("Config file \"%s\" is readable by others (permissions=%s). If you are config "
                "file contains secrets (e.g. password) you are strongly encouraged to make sure "
                "it's not readable by other users (chmod 600 %s)" % (file_path, file_permissions,
                                                                     file_path))

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
    self.viewer.setWindowTitle("rMview - " + ssh.hostname)

    _,out,_ = ssh.exec_command("cat /sys/devices/soc0/machine")
    rmv = out.read().decode("utf-8")
    version = re.fullmatch(r"reMarkable(?: Prototype)? (\d+)(\.\d+)*\n", rmv)
    if version is None or version[1] not in ["1", "2"]:
      log.error("Device is unsupported: '%s' [%s]", rmv.strip(), version[1] if version else "unknown device")
      QMessageBox.critical(None, "Unsupported device", "The detected device is '%s'.\nrmView currently only supports reMarkable 1 and 2." % rmv.strip())
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

    self.fbworker = FrameBufferWorker(ssh, ssh_config=self.config.get('ssh', {}),
                                      delay=self.config.get('fetch_frame_delay'))
    self.fbworker.signals.onNewFrame.connect(self.onNewFrame)
    self.fbworker.signals.onFatalError.connect(self.frameError)
    self.threadpool.start(self.fbworker)
    if self.config.get("forward_mouse_events", True):
      self.viewer.pointerEvent.connect(self.fbworker.pointerEvent)

    self.penworker = PointerWorker(ssh, path="/dev/input/event%d" % (version-1))
    self.threadpool.start(self.penworker)
    self.pen = self.viewer.scene.addEllipse(0,0,self.pen_size,self.pen_size,
                                            pen=QPen(QColor('white')),
                                            brush=QBrush(QColor(self.config.get('pen_color', 'red'))))
    self.pen.lastShown = None
    self.pen.showDelay = self.config.get("pen_show_delay", 0.4)
    self.pen.hide()
    self.pen.setZValue(100)
    self.penworker.signals.onPenMove.connect(self.movePen)
    if self.config.get("show_pen_on_lift", True):
      self.penworker.signals.onPenLift.connect(self.showPen)
    if self.config.get("hide_pen_on_press", True):
        self.penworker.signals.onPenPress.connect(self.hidePen)
    self.penworker.signals.onPenNear.connect(self.showPenNow)
    self.penworker.signals.onPenFar.connect(self.hidePen)


  @pyqtSlot(QImage)
  def onNewFrame(self, image):
    if self.orient > 0:
      self.detectOrientation(image)
      if self.orient == 1:
        self.orient = 0
    self.viewer.setImage(image)

  @pyqtSlot()
  def hidePen(self):
    if self.trail is not None:
      self.trail = False
    self.pen.lastShown = None
    self.pen.hide()

  @pyqtSlot()
  def showPen(self):
    if self.trail is not None:
      self.trail = False
    self.pen.lastShown = time.perf_counter()
    # self.pen.show()

  @pyqtSlot()
  def showPenNow(self):
    if self.trail is not None:
      self.trail = False
    self.pen.lastShown = None
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
    if self.pen.lastShown is not None:
      if time.perf_counter() - self.pen.lastShown > self.pen.showDelay:
        self.pen.show()
        self.pen.lastShown = None

  @pyqtSlot()
  def cloneViewer(self):
    img = self.viewer.image()
    v = QtImageViewer()
    v.setImage(img)
    v.show()

  @pyqtSlot()
  def toggleStreaming(self):
    if self.streaming:
      self.fbworker.pause()
      self.penworker.pause()
      self.streaming = False
      self.pauseAction.setText("Resume Streaming")
      self.viewer.setWindowTitle("rMview - " + self.ssh.hostname + " [PAUSED]")
    else:
      self.fbworker.resume()
      self.penworker.resume()
      self.streaming = True
      self.pauseAction.setText("Pause Streaming")
      self.viewer.setWindowTitle("rMview - " + self.ssh.hostname)

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

  def event(self, e):
    return QApplication.event(self, e)

def rmViewMain():
  log.setLevel(logging.INFO)
  QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
  app = rMViewApp(sys.argv)
  # We register custom signal handler so we can gracefuly stop app with CTRL+C when QT main loop is
  # running
  signal.signal(signal.SIGINT, lambda *args: app.quit())
  app.startTimer(500)
  ecode = app.exec_()
  print('\nBye!')
  sys.exit(ecode)

if __name__ == '__main__':
  rmViewMain()
