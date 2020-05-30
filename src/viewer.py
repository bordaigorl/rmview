from PyQt5.QtCore import Qt, QRectF, pyqtSignal, QT_VERSION_STR
from PyQt5.QtGui import QImage, QPixmap, QTransform, QIcon
from PyQt5.QtWidgets import QGraphicsView, QGraphicsScene, QFileDialog, QAction, QMenu


class QtImageViewer(QGraphicsView):

  zoomInFactor = 1.25
  zoomOutFactor = 1 / zoomInFactor

  def __init__(self):
    QGraphicsView.__init__(self)
    # self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    self.scene = QGraphicsScene()
    self.setScene(self.scene)

    self._pixmap = None
    self.aspectRatioMode = Qt.KeepAspectRatio
    self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    self.setAlignment(Qt.AlignCenter)

    self.menu = QMenu(self)
    act = QAction('Fit to view', self, checkable=True)
    self.fitAction = act
    act.triggered.connect(lambda: self.setFit(True))
    self.menu.addAction(act)
    ###
    act = QAction('Actual Size', self)
    act.triggered.connect(lambda: self.actualSize())
    self.menu.addAction(act)
    ###
    act = QAction('Zoom In', self)
    act.triggered.connect(self.zoomIn)
    self.menu.addAction(act)
    ###
    act = QAction('Zoom Out', self)
    act.triggered.connect(self.zoomOut)
    self.menu.addAction(act)
    ###
    self.menu.addSeparator() # --------------------------
    ###
    act = QAction('Rotate clockwise', self)
    act.triggered.connect(self.rotateCW)
    self.menu.addAction(act)
    ###
    act = QAction('Rotate counter-clockwise', self)
    act.triggered.connect(self.rotateCCW)
    self.menu.addAction(act)
    ###
    self.menu.addSeparator() # --------------------------
    ###
    act = QAction('Save screenshot', self)
    act.triggered.connect(self.screenshot)
    self.menu.addAction(act)

    self._fit = True
    self._rotation = 0 # used to produce a rotated screenshot

  def contextMenuEvent(self, event):
    self.fitAction.setChecked(self._fit)
    self.menu.exec_(self.mapToGlobal(event.pos()))

  def hasImage(self):
    return self._pixmap is not None

  def clearImage(self):
    if self.hasImage():
      self.scene.removeItem(self._pixmap)
      self._pixmap = None

  def pixmap(self):
    if self.hasImage():
      return self._pixmap.pixmap()
    return None

  def image(self):
    if self.hasImage():
      return self._pixmap.pixmap().toImage()
    return None

  def setImage(self, image):
    if type(image) is QPixmap:
      pixmap = image
    elif type(image) is QImage:
      pixmap = QPixmap.fromImage(image)
    else:
      raise RuntimeError("ImageViewer.setImage: Argument must be a QImage or QPixmap.")
    if self.hasImage():
      self._pixmap.setPixmap(pixmap)
    else:
      self._pixmap = self.scene.addPixmap(pixmap)
      self._pixmap.setZValue(-1)
    self._pixmap.setTransformationMode(Qt.SmoothTransformation)
    self.setSceneRect(QRectF(pixmap.rect()))  # Set scene size to image size.
    # self.fitInView(self.sceneRect(), self.aspectRatioMode)  # Show entire image (use current aspect ratio mode).
    self.updateViewer()

  def updateViewer(self):
    if self.hasImage() is None:
      return
    if self._fit:
      self.fitInView(self.sceneRect(), self.aspectRatioMode)
    # else:

  def resizeEvent(self, event):
    self.updateViewer()

  def mouseDoubleClickEvent(self, event):
    # scenePos = self.mapToScene(event.pos())
    if event.button() == Qt.LeftButton:
        self._fit=True
        self.updateViewer()
        # self.leftMouseButtonDoubleClicked.emit(scenePos.x(), scenePos.y())
    # elif event.button() == Qt.RightButton:
        # self.rightMouseButtonDoubleClicked.emit(scenePos.x(), scenePos.y())
    QGraphicsView.mouseDoubleClickEvent(self, event)


  def wheelEvent(self, event):
    if event.modifiers() == Qt.NoModifier:
      QGraphicsView.wheelEvent(self, event)
    else:
      self._fit = False

      self.setTransformationAnchor(QGraphicsView.NoAnchor)
      self.setResizeAnchor(QGraphicsView.NoAnchor)

      oldPos = self.mapToScene(event.pos())

      # Zoom
      if event.angleDelta().y() > 0:
          zoomFactor = self.zoomInFactor
      else:
          zoomFactor = self.zoomOutFactor
      self.scale(zoomFactor, zoomFactor)

      # Get the new position
      newPos = self.mapToScene(event.pos())

      # Move scene to old position
      delta = newPos - oldPos
      self.translate(delta.x(), delta.y())

  def screenshot(self):
    img = self.image()
    if img is not None:
      fileName, ok = QFileDialog.getSaveFileName(self, "Save screenshot...", "rm-screenshot.png")
      if ok and fileName:
        img = img.transformed(QTransform().rotate(self._rotation))
        img.save(fileName)

  def landscape(self):
    self.resetTransform()
    self.rotate(90)
    self._rotation = 90
    self.updateViewer()

  def portrait(self):
    self.resetTransform()
    self._rotation = 0
    self.updateViewer()

  def rotateCW(self):
    self.rotate(90)
    self._rotation += 90
    self.updateViewer()

  def rotateCCW(self):
    self.rotate(-90)
    self._rotation -= 90
    self.updateViewer()

  def zoomIn(self):
    self._fit = False
    self.scale(self.zoomInFactor, self.zoomInFactor)

  def zoomOut(self):
    self._fit = False
    self.scale(self.zoomOutFactor, self.zoomOutFactor)

  def setFit(self, f):
    self._fit = f
    self.updateViewer()

  def actualSize(self):
    self._fit = False
    self.resetTransform()
    self.scale(1/self.devicePixelRatio(), 1/self.devicePixelRatio())
    self.rotate(self._rotation)

  def keyPressEvent(self, event):
    if event.key() == Qt.Key_Left:
      self.rotateCCW()
    elif event.key() == Qt.Key_Right:
      self.rotateCW()
    elif event.key() == Qt.Key_F:
      self.setFit(True)
    elif event.key() == Qt.Key_1:
      self.actualSize()
    elif event.key() == Qt.Key_S:
      self.screenshot()
    elif event.key() == Qt.Key_Plus:
      self.zoomIn()
    elif event.key() == Qt.Key_Minus:
      self.zoomOut()

