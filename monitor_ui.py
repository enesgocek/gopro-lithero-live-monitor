"""Image-first desktop UI with edge-revealed controls."""
from i18n import tr
import cv2
import numpy as np
from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QImage, QPainter, QColor, QFont
from PyQt6.QtWidgets import (QWidget,QFrame,QLabel,QPushButton,QCheckBox,QComboBox,
    QLineEdit,QSpinBox,QVBoxLayout,QHBoxLayout,QFormLayout,QGroupBox,QScrollArea,QPlainTextEdit,QProgressBar)

STYLE = '''
QWidget { color: #eef1f4; font-family: 'Segoe UI'; font-size: 13px; }
QMainWindow { background: #080a0d; }
QFrame#panel { background: rgba(18, 22, 28, 246); border: 1px solid #303640; border-radius: 18px; }
QFrame#topbar { background: rgba(18, 22, 28, 240); border: 1px solid #303640; border-radius: 16px; }
QLabel { background: transparent; border: none; }
QLabel#muted { color: #8b95a3; font-size: 12px; }
QLabel#status { color: #9ba6b5; font-size: 12px; }
QPushButton { background: #252c36; color: #edf1f5; border: 1px solid transparent; border-radius: 9px; padding: 10px 12px; min-height: 18px; }
QPushButton:hover { background: #343e4a; border-color: #485460; }
QPushButton:pressed { background: #1d232b; }
QPushButton:disabled { background: #1c2128; color: #58616d; }
QPushButton#primary { background: #e1e8ee; color: #11161c; font-weight: 600; }
QPushButton#primary:hover { background: #ffffff; }
QPushButton#record { background: #962e3c; font-weight: 600; }
QPushButton#record:hover { background: #b43748; }
QPushButton#record:disabled { background: #302127; color: #735661; }
QPushButton#quiet { background: transparent; padding: 7px 10px; }
QPushButton#quiet:hover { background: #303844; }
QLineEdit,QSpinBox,QComboBox,QPlainTextEdit { background: #0e1218; color: #dce3eb; border: 1px solid #303844; border-radius: 8px; padding: 8px; }
QComboBox:disabled,QLineEdit:disabled,QSpinBox:disabled { color: #647080; }
QGroupBox { background: transparent; border: none; border-top: 1px solid #303640; margin-top: 22px; padding-top: 18px; }
QGroupBox::title { subcontrol-origin: margin; left: 0; padding-right: 10px; color: #9faab7; }
QCheckBox { background: transparent; spacing: 8px; padding: 3px 0; }
QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #657181; border-radius: 4px; background: #131820; }
QCheckBox::indicator:checked { background: #cad8e5; border-color: #cad8e5; }
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 5px; margin: 4px; }
QScrollBar::handle:vertical { background: #44515f; border-radius: 2px; min-height: 25px; }
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical { background: transparent; }
'''

class VideoCanvas(QWidget):
    double_clicked = pyqtSignal()
    def __init__(self,parent=None):
        super().__init__(parent)
        self.image = None
        self.message = tr('Kameranız için sakin bir çalışma alanı.')
        self.mirrored = False
        self.fill = False
        self.setMouseTracking(True)

    def clear(self):
        self.image = None
        self.update()

    def setText(self,text):
        self.message = text
        self.update()

    def set_frame(self,frame):
        pixels=np.ascontiguousarray(frame)
        h,w,_=pixels.shape
        self.image=QImage(pixels.data,w,h,pixels.strides[0],QImage.Format.Format_BGR888).copy()
        self.update()

    def paintEvent(self,event):
        painter=QPainter(self)
        painter.fillRect(self.rect(),QColor('#050608'))
        if self.image and not self.image.isNull():
            w,h=self.image.width(),self.image.height()
            scale=max(self.width()/w,self.height()/h) if self.fill else min(self.width()/w,self.height()/h)
            dw,dh=w*scale,h*scale
            target=QRectF((self.width()-dw)/2,(self.height()-dh)/2,dw,dh)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            if self.mirrored:
                painter.translate(self.width(),0)
                painter.scale(-1,1)
            painter.drawImage(target,self.image)
        else:
            painter.setPen(QColor('#737f8e'))
            painter.setFont(QFont('Segoe UI',14))
            painter.drawText(self.rect().adjusted(70,50,-70,-50),Qt.AlignmentFlag.AlignCenter|Qt.TextFlag.TextWordWrap,self.message)

    def mouseDoubleClickEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)

def panel(parent,name):
    frame=QFrame(parent)
    frame.setObjectName(name)
    frame.setMouseTracking(True)
    return frame

def muted(text):
    label=QLabel(text)
    label.setObjectName('muted')
    label.setWordWrap(True)
    return label

def button(text,action,kind=None):
    result=QPushButton(text)
    if kind:result.setObjectName(kind)
    result.clicked.connect(action)
    return result

def build_ui(window):
    window.surface=QWidget()
    window.surface.setMouseTracking(True)
    window.setCentralWidget(window.surface)
    window.video_label=VideoCanvas(window.surface)
    window.video_label.double_clicked.connect(window.toggle_fullscreen)
    window.top_bar=panel(window.surface,'topbar')
    top=QHBoxLayout(window.top_bar)
    top.setContentsMargins(18,8,12,8)
    logo=QLabel('GoPro LitHero Live Monitor')
    logo.setStyleSheet('font-size: 15px; font-weight: 600; letter-spacing: 2px;')
    top.addWidget(logo)
    window.preview_badge=QLabel(tr('BAĞLANTI YOK'))
    window.preview_badge.setObjectName('muted')
    top.addSpacing(14)
    top.addWidget(window.preview_badge)
    top.addStretch()
    top.addWidget(button(tr('Bağlantı'),window.toggle_connection_panel,'quiet'))
    top.addWidget(button(tr('Kontroller'),window.toggle_control_panel,'quiet'))
    window.fullscreen_button=button(tr('Tam ekran  ↗'),window.toggle_fullscreen,'quiet')
    top.addWidget(window.fullscreen_button)
    top.addWidget(button(tr('×'),window.close,'quiet'))

    window.left_panel=panel(window.surface,'panel')
    left_shell=QVBoxLayout(window.left_panel)
    left_shell.setContentsMargins(18,18,18,18)
    left_shell.addWidget(QLabel(tr('BAĞLANTI')))
    scroll=QScrollArea()
    scroll.setWidgetResizable(True)
    content=QWidget()
    content.setObjectName('drawerContent')
    content.setStyleSheet('QWidget#drawerContent { background: transparent; }')
    left=QVBoxLayout(content)
    left.setContentsMargins(0,10,6,0)
    left.setSpacing(12)
    window.camera_label=QLabel(tr('Kamera henüz bağlı değil'))
    window.camera_label.setWordWrap(True)
    left.addWidget(window.camera_label)
    window.telemetry=muted(tr('Pil: —   SD: —'))
    left.addWidget(window.telemetry)
    window.connect_button=button(tr('Tek tuşla bağlan'),window.quick_connect,'primary')
    left.addWidget(window.connect_button)
    window.remember_camera=QCheckBox(tr('Bu kamerayı hatırla'))
    window.auto_connect=QCheckBox(tr('Açılışta otomatik bağlan'))
    left.addWidget(window.remember_camera)
    left.addWidget(window.auto_connect)
    language_row=QHBoxLayout()
    language_row.addWidget(QLabel(tr('Dil')))
    window.language_combo=QComboBox()
    window.language_combo.addItem('English','en')
    window.language_combo.addItem('Türkçe','tr')
    language_row.addWidget(window.language_combo,1)
    left.addLayout(language_row)
    left.addWidget(muted(tr('Kayıtlı Windows ağı kullanılır; şifre yazmanız gerekmez.')))
    window.setup_toggle=QCheckBox(tr('Bluetooth / Wi-Fi kurulumu'))
    window.setup_toggle.setChecked(False)
    left.addWidget(window.setup_toggle)
    setup=QGroupBox(tr('Kamera ağını hazırla'))
    window.setup_group=setup
    window.setup_toggle.toggled.connect(setup.setVisible)
    setup.setVisible(False)
    layout=QVBoxLayout(setup)
    layout.setContentsMargins(0,12,0,0)
    layout.setSpacing(10)
    layout.addWidget(muted(tr('Kamerada Quik / uygulama eşleştirme ekranını açın.')))
    window.scan_button=button(tr('Bluetooth ile ara'),window.scan_bluetooth)
    layout.addWidget(window.scan_button)
    window.device_combo=QComboBox()
    window.device_combo.setMinimumContentsLength(12)
    layout.addWidget(window.device_combo)
    window.prepare_button=button(tr('Kamera Wi-Fi ağını aç'),window.prepare_wifi)
    layout.addWidget(window.prepare_button)
    window.ssid_label=muted(tr('Kamera ağı: —'))
    layout.addWidget(window.ssid_label)
    window.password_field=QLineEdit()
    window.password_field.setReadOnly(True)
    window.password_field.setPlaceholderText(tr('Parola Bluetooth ile otomatik alınır'))
    window.password_field.setEchoMode(QLineEdit.EchoMode.Password)
    window.password_field.hide()
    layout.addWidget(muted(tr('Parola otomatik alınır ve Windows Wi-Fi profiline kaydedilir.')))
    window.wifi_button=button(tr('Windows’u kamera ağına bağla'),window.connect_wifi)
    layout.addWidget(window.wifi_button)
    left.addWidget(setup)
    advanced_toggle=QCheckBox(tr('Gelişmiş bağlantı'))
    advanced=QWidget()
    form=QFormLayout(advanced)
    form.setContentsMargins(0,4,0,4)
    window.address=QLineEdit('10.5.5.9')
    window.port=QSpinBox()
    window.port.setRange(1024,65535)
    window.port.setValue(8554)
    form.addRow(tr('Kamera IP'),window.address)
    form.addRow(tr('UDP portu'),window.port)
    form.addRow(button(tr('Yalnızca mevcut IP ile bağlan'),window.connect_camera))
    advanced_toggle.toggled.connect(advanced.setVisible)
    left.addWidget(advanced_toggle)
    left.addWidget(advanced)
    advanced.hide()
    left.addStretch()
    scroll.setWidget(content)
    left_shell.addWidget(scroll)

    window.right_panel=panel(window.surface,'panel')
    right_shell=QVBoxLayout(window.right_panel)
    right_shell.setContentsMargins(12,12,12,12)
    right_scroll=QScrollArea()
    right_scroll.setWidgetResizable(True)
    right_content=QWidget()
    right_content.setObjectName('rightContent')
    right_content.setStyleSheet('QWidget#rightContent { background: transparent; }')
    right=QVBoxLayout(right_content)
    right.setContentsMargins(8,8,8,8)
    right.setSpacing(14)
    right.addWidget(QLabel(tr('ÇEKİM')))
    window.record_badge=muted(tr('SD kaydı: durum bilinmiyor'))
    right.addWidget(window.record_badge)
    window.record_button=button(tr('Kaydı başlat'),window.toggle_recording,'record')
    right.addWidget(window.record_button)
    right.addWidget(muted(tr('Kayıt kameranın SD kartına yapılır.')))
    window.quality_photo_button=button(tr('Kaliteli test fotoğrafı · F8'),lambda:window.capture_quality('photo'),'primary')
    window.quality_photo_button.setToolTip(tr('Doğrudan 12 MP fotoğraf. Geçicidir; kapatınca canlı önizlemeye dönülür.'))
    right.addWidget(window.quality_photo_button)
    window.quality_video_button=button(tr('Video kadrajından kare'),lambda:window.capture_quality('video'))
    window.quality_video_button.setToolTip(tr('Orijinal çözünürlüklü test karesi. Yalnızca bellekte tutulur; kapatınca silinir.'))
    right.addWidget(window.quality_video_button)
    right.addWidget(muted(tr('Fotoğraf 4:3 kadrajındadır. Video karesi seçili video ayarını kullanır. Kapatınca silinir ve canlıya dönülür.')))
    window.start_button=button(tr('Önizlemeyi başlat'),window.start_stream)
    window.stop_button=button(tr('Önizlemeyi durdur'),window.stop_stream)
    right.addWidget(window.start_button)
    right.addWidget(window.stop_button)
    window.source_label=muted(tr('Kaynak: —'))
    right.addWidget(window.source_label)
    right.addWidget(muted(tr('Canlı görüntü, kameranın gönderdiği doğal çözünürlükte alınır.')))
    window.mirror=QCheckBox(tr('Aynala'))
    window.mirror.toggled.connect(lambda:window.display_frame())
    right.addWidget(window.mirror)
    window.fill_toggle=QCheckBox(tr('Ekranı doldur'))
    window.fill_toggle.setToolTip(tr('Kenarları kırpar. Kapalıyken tüm kadraj görünür.'))
    window.fill_toggle.toggled.connect(lambda:window.display_frame())
    right.addWidget(window.fill_toggle)
    right.addWidget(button(tr('Günlük'),window.toggle_log_panel,'quiet'))
    right.addStretch()
    right_scroll.setWidget(right_content)
    right_shell.addWidget(right_scroll)

    window.capture_toast=panel(window.surface,'panel')
    toast=QVBoxLayout(window.capture_toast)
    toast.setContentsMargins(20,14,20,14)
    window.capture_progress_label=QLabel(tr('Kaliteli kadraj hazırlanıyor…'))
    window.capture_progress_label.setWordWrap(True)
    toast.addWidget(window.capture_progress_label)
    progress=QProgressBar()
    progress.setRange(0,0)
    progress.setTextVisible(False)
    progress.setFixedHeight(5)
    progress.setStyleSheet('QProgressBar { border: none; background: #252c36; border-radius: 2px; } QProgressBar::chunk { background: #e1e8ee; }')
    toast.addWidget(progress)
    window.capture_toast.hide()

    window.log_panel=panel(window.surface,'panel')
    logs=QVBoxLayout(window.log_panel)
    logs.setContentsMargins(16,14,16,14)
    log_top=QHBoxLayout()
    log_top.addWidget(QLabel(tr('BAĞLANTI GÜNLÜĞÜ')))
    log_top.addStretch()
    log_top.addWidget(button(tr('Kapat'),window.log_panel.hide,'quiet'))
    logs.addLayout(log_top)
    window.log_view=QPlainTextEdit()
    window.log_view.setReadOnly(True)
    window.log_view.document().setMaximumBlockCount(300)
    logs.addWidget(window.log_view)
    window.status_label=QLabel(tr('Bağlantı → Kameraya bağlan.  F11 veya çift tık: yalnızca görüntü.'))
    window.status_label.setObjectName('status')
    window.status_label.setWordWrap(True)
    window.status_label.setParent(window.surface)
    window.edge_hint=QLabel(tr('SOL · BAĞLANTI     ÜST · GÖRÜNÜM     SAĞ · ÇEKİM'))
    window.edge_hint.setObjectName('muted')
    window.edge_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
    window.edge_hint.setParent(window.surface)
    window.left_panel.show()
    window.right_panel.hide()
    window.log_panel.hide()
    window.edge_hint.hide()
    window.device_combo.currentIndexChanged.connect(window.update_controls)
    for widget in window.surface.findChildren(QWidget):widget.setMouseTracking(True)
