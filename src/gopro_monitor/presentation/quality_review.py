"""Inspect original camera stills at native resolution, with pan and zoom."""
from gopro_monitor.presentation.localization import retranslate_widgets
from gopro_monitor.shared.i18n import tr
import numpy as np
from PyQt6.QtCore import Qt,QTimer,pyqtSignal
from PyQt6.QtGui import QPixmap,QImage,QShortcut,QKeySequence
from PyQt6.QtWidgets import QDialog,QGraphicsView,QGraphicsScene,QVBoxLayout,QHBoxLayout,QLabel,QPushButton
from gopro_monitor.presentation.monitor_ui import STYLE
from gopro_monitor.shared.i18n import language

class ReviewView(QGraphicsView):
    zoom_changed=pyqtSignal(float)
    def __init__(self,parent=None):
        super().__init__(parent)
        self.scene=QGraphicsScene(self)
        self.setScene(self.scene)
        self.item=None
        self.setBackgroundBrush(Qt.GlobalColor.black)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.fit_mode=True

    def set_pixmap(self,pixmap):
        self.scene.clear()
        self.item=self.scene.addPixmap(pixmap)
        self.scene.setSceneRect(self.item.boundingRect())
        self.fit_image()

    def fit_image(self):
        self.fit_mode=True
        if self.item:
            self.fitInView(self.item,Qt.AspectRatioMode.KeepAspectRatio)
            self.zoom_changed.emit(self.transform().m11())

    def actual_size(self):
        self.fit_mode=False
        self.resetTransform()
        self.zoom_changed.emit(1)

    def zoom(self,factor):
        self.fit_mode=False
        current=self.transform().m11()
        new=min(8,max(.05,current*factor))
        self.scale(new/current,new/current)
        self.zoom_changed.emit(new)

    def wheelEvent(self,event):
        self.zoom(1.2 if event.angleDelta().y()>0 else 1/1.2)
        event.accept()

    def mouseDoubleClickEvent(self,event):
        self.actual_size() if self.fit_mode else self.fit_image()
        event.accept()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self.fit_mode:self.fit_image()

class QualityReview(QDialog):
    discarded=pyqtSignal()
    def __init__(self,capture,parent=None):
        super().__init__(parent)
        self.capture={key:value for key,value in capture.items() if key!='frame'}
        self._discarded=False
        self.setWindowTitle(tr('Kaliteli kadraj · LIT HERO'))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setStyleSheet(STYLE+'QDialog { background: #10151c; }')
        self.resize(1280,900)
        self.setMinimumSize(760,520)
        layout=QVBoxLayout(self)
        layout.setContentsMargins(18,14,18,14)
        top=QHBoxLayout()
        kind=tr('VİDEO KARESİ') if capture['kind']=='video' else tr('FOTOĞRAF')
        self.info=QLabel(tr('{0}  ·  {1} × {2}').format(kind, capture["width"], capture["height"]))
        top.addWidget(self.info)
        top.addStretch()
        self.zoom_label=QLabel('')
        self.zoom_label.setMinimumWidth(52)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.zoom_label)
        self.view=ReviewView(self)
        for text,action in [(tr('Sığdır'),self.view.fit_image),('100%',self.view.actual_size),(tr('−'),lambda:self.view.zoom(1/1.2)),('+',lambda:self.view.zoom(1.2)),(tr('Tam ekran'),self.toggle_fullscreen),(tr('Canlıya dön'),self.close)]:
            button=QPushButton(text)
            button.clicked.connect(action)
            top.addWidget(button)
        layout.addLayout(top)
        layout.addWidget(self.view,1)
        description=tr('Geçici kare · kapatınca silinir. Fare tekerleği: büyüt • Sürükle: gezin • 100%: gerçek piksel boyutu.')
        if capture['kind']=='photo':description+=tr(' Fotoğraf 4:3 modundadır; video kadrajı ve pozlaması farklı olabilir.')
        if capture.get('cleanup_warning'):description+=' '+capture['cleanup_warning']
        if capture.get('restore_warning'):description+=' '+capture['restore_warning']
        label=QLabel(description)
        label.setWordWrap(True)
        label.setObjectName('muted')
        layout.addWidget(label)
        frame=capture.get('frame')
        if not isinstance(frame,np.ndarray) or frame.dtype!=np.uint8 or frame.ndim!=3 or frame.shape[2]!=3:
            raise ValueError(tr('Geçici görüntü karesi geçersiz.'))
        frame=np.ascontiguousarray(frame)
        height,width=frame.shape[:2]
        image=QImage(frame.data,width,height,frame.strides[0],QImage.Format.Format_BGR888).copy()
        if image.isNull():raise ValueError(tr('Yüksek çözünürlüklü görsel açılamadı.'))
        self.view.zoom_changed.connect(lambda value:self.zoom_label.setText(f'%{value*100:.0f}'))
        self.view.set_pixmap(QPixmap.fromImage(image))
        QTimer.singleShot(0,self.view.fit_image)
        self.shortcut=QShortcut(QKeySequence('F11'),self)
        self.shortcut.activated.connect(self.toggle_fullscreen)
        retranslate_widgets(self,language())

    def toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def discard(self):
        if self._discarded:return
        self._discarded=True
        self.view.scene.clear()
        self.view.item=None
        self.capture.clear()
        self.discarded.emit()

    def done(self,result):
        self.discard()
        super().done(result)

    def closeEvent(self,event):
        self.discard()
        super().closeEvent(event)
