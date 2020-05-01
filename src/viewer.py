""" QtImageViewer.py: PyQt image viewer widget for a QPixmap in a QGraphicsView scene with mouse zooming and panning.

"""

from PyQt5.QtCore import Qt, QRectF, pyqtSignal, QT_VERSION_STR
from PyQt5.QtGui import QImage, QPixmap, QTransform
from PyQt5.QtWidgets import QGraphicsView, QGraphicsScene, QFileDialog, QAction, QMenu


class QtImageViewer(QGraphicsView):

    def __init__(self):
      QGraphicsView.__init__(self)
      self.setAttribute(Qt.WA_OpaquePaintEvent, True)

      self.scene = QGraphicsScene()
      self.setScene(self.scene)

      self._pixmap = None
      self.aspectRatioMode = Qt.KeepAspectRatio
      self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
      self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
      self.setAlignment(Qt.AlignCenter)

      self.menu = QMenu(self)
      act = QAction('Fit to view', self)
      # act.setShortcut('Ctrl+S')
      act.triggered.connect(lambda: self.setFit(True))
      self.menu.addAction(act)
      act = QAction('Rotate clockwise', self)
      # act.setShortcut('Ctrl+Right')
      act.triggered.connect(self.rotateCW)
      self.menu.addAction(act)
      act = QAction('Rotate counter-clockwise', self)
      # act.setShortcut('Ctrl+Left')
      act.triggered.connect(self.rotateCCW)
      self.menu.addAction(act)
      self.menu.addSeparator()
      act = QAction('Save screenshot', self)
      # act.setShortcut('Ctrl+S')
      act.triggered.connect(self.screenshot)
      self.menu.addAction(act)

      self._fit = True
      self._rotation = 0 # used to produce a rotated screenshot

    def contextMenuEvent(self, event):
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

            # Zoom Factor
            zoomInFactor = 1.25
            zoomOutFactor = 1 / zoomInFactor

            # Set Anchors
            self.setTransformationAnchor(QGraphicsView.NoAnchor)
            self.setResizeAnchor(QGraphicsView.NoAnchor)

            # Save the scene pos
            oldPos = self.mapToScene(event.pos())

            # Zoom
            if event.angleDelta().y() > 0:
                zoomFactor = zoomInFactor
            else:
                zoomFactor = zoomOutFactor
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
          print(self._rotation)
          img = img.transformed(QTransform().rotate(self._rotation));
          img.save(fileName)

    def rotateCW(self):
        self.rotate(90)
        self._rotation += 90
        self.updateViewer()

    def rotateCCW(self):
        self.rotate(-90)
        self._rotation -= 90
        self.updateViewer()

    def setFit(self, f):
      self._fit = f
      self.updateViewer()

    def keyPressEvent(self, event):
      if event.key() == Qt.Key_Left:
        self.rotateCCW()
      elif event.key() == Qt.Key_Right:
        self.rotateCW()
      elif event.key() == Qt.Key_1:
        self.setFit(True)
      elif event.key() == Qt.Key_S:
        self.screenshot()

