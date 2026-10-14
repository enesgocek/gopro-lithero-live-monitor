"""Turkish desktop monitor for GoPro LIT HERO."""
from i18n import tr, language, set_language, retranslate_widgets
from privacy import redact
import argparse
from collections import deque
from datetime import datetime
from pathlib import Path
import sys
import time
import cv2
import numpy as np
from PyQt6.QtCore import Qt, QTimer, QEvent
from PyQt6.QtGui import QShortcut, QKeySequence
from urllib.parse import urlsplit
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QSpinBox, QComboBox,
    QCheckBox, QPlainTextEdit, QGroupBox, QSplitter, QScrollArea)
from camera_api import validate_address, CameraError
from gopro_controller import GoProController
from video_stream import VideoStreamThread
from ble_setup import BluetoothWorker
from wifi_connect import WifiConnectWorker
from quick_connection import QuickConnectionWorker
from connection_store import ConnectionStore
from quality_review import QualityReview

from monitor_ui import STYLE, build_ui

class MainWindow(QMainWindow):
    def __init__(self, demo=False,settings_path=None,ui_language=None):
        super().__init__()
        self.setWindowTitle('GoPro LitHero Live Monitor')
        self.resize(1280, 820)
        self.setMinimumSize(900, 680)
        self.setStyleSheet(STYLE)
        self.demo = demo
        self.connection_store=ConnectionStore(settings_path)
        self.connection_profile=self.connection_store.load()
        set_language(ui_language or self.connection_profile['language'])
        self.setWindowTitle('GoPro LitHero Live Monitor')
        self.connection_worker=None
        self._quick_connecting=False
        self._auto_start_on_connect=False
        self._saving_connection=False
        self._transport='Wi-Fi'
        self._connected = False
        self._recording = None
        self._pending = set()
        self._closing = False
        self._close_started = 0
        self._preview_state = 'stopped'
        self._frame = None
        self._last_frame_time = 0
        # empty credential default / reference release, not a secret.
        self._ssid = self._password = ''  # nosec B105
        self.stream_thread = None
        self.bluetooth_worker = None
        self.wifi_worker = None
        self._workers = []
        self._queued_stream_url = None
        self._reviews = []
        self._return_to_live=False
        self._live_resume_attempts=0
        self._live_restart_at=0
        self._live_return_timer=QTimer(self)
        self._live_return_timer.setInterval(200)
        self._live_return_timer.timeout.connect(self.check_return_to_live)
        self._log_lines = deque(maxlen=300)
        self._demo_tick = 0
        self._focus_mode = False
        self._last_pointer = None
        self._edge_hide_timer = QTimer(self)
        self._edge_hide_timer.setSingleShot(True)
        self._edge_hide_timer.timeout.connect(self.hide_edge_panels)
        self._build_ui()
        profile=self.connection_profile
        self.address.setText(profile['address'])
        self.port.setValue(profile['port'])
        self._ssid=profile['ssid']
        if self._ssid:self.ssid_label.setText(tr('Kayıtlı kamera ağı: ')+self._ssid)
        if profile['device']:self.device_combo.addItem(profile['device_name'] or tr('Hatırlanan GoPro'),profile['device'])
        self.remember_camera.setChecked(profile['remember'])
        self.auto_connect.setChecked(profile['auto_connect'])
        self.auto_connect.setEnabled(profile['remember'])
        self.language_combo.setCurrentIndex(self.language_combo.findData(language()))
        self.language_combo.currentIndexChanged.connect(self.change_language)
        retranslate_widgets(self,language())
        self.remember_camera.toggled.connect(self.save_connection_profile)
        self.auto_connect.toggled.connect(self.save_connection_profile)
        self.address.editingFinished.connect(self.save_connection_profile)
        self.port.editingFinished.connect(self.save_connection_profile)
        self.gopro = GoProController(self)
        self.gopro.connection_status.connect(self.show_status)
        self.gopro.connected.connect(self.on_connected)
        self.gopro.camera_info.connect(self.on_info)
        self.gopro.camera_state.connect(self.on_camera_state)
        self.gopro.decoder_requested.connect(self.on_stream_url_ready)
        self.gopro.preview_stopped.connect(self.stop_decoder)
        self.gopro.command_finished.connect(self.on_command_finished)
        self.gopro.debug_signal.connect(self.log)
        self.gopro.quality_ready.connect(self.on_quality_ready)
        self.gopro.resume_preview_requested.connect(self.request_return_to_live)
        self.gopro.start()
        self.render_timer = QTimer(self)
        self.render_timer.timeout.connect(self.render_frame)
        self.render_timer.start(16)
        QApplication.instance().installEventFilter(self)
        self.close_timer = QTimer(self)
        self.close_timer.timeout.connect(self.finish_close)
        self._shortcuts = []
        for key, action in [('F11', self.toggle_fullscreen), ('Esc', self.escape),
                            ('F8',lambda:self.capture_quality('photo'))]:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(action)
            self._shortcuts.append(shortcut)
        if self.demo:
            self.show_status(tr('DEMO — Sentetik görüntü; kamera bağlantısı ve SD kaydı yok.'))
            self.camera_label.setText(tr('DEMO • Gerçek kamera bağlı değil'))
            self.preview_badge.setText(tr('DEMO GÖRÜNTÜSÜ'))
        self.update_controls()

    def _build_ui(self):
        build_ui(self)
        self.layout_overlays()

    def change_language(self):
        previous=language()
        set_language(self.language_combo.currentData())
        retranslate_widgets(self,previous)
        self.update_controls()
        self.save_connection_profile()

    def layout_overlays(self):
        if not hasattr(self, 'top_bar'):
            return
        w, h = self.surface.width(), self.surface.height()
        self.video_label.setGeometry(0, 0, w, h)
        self.top_bar.setGeometry(20, 16, max(100, w-40), 60)
        self.left_panel.setGeometry(20, 88, min(344, w-40), max(120, h-136))
        self.right_panel.setGeometry(max(20,w-330), 88, 310, max(120,min(720,h-136)))
        self.log_panel.setGeometry(max(20,(w-760)//2),max(90,h-260),min(760,w-40),210)
        self.status_label.setGeometry(28,max(0,h-38),max(100,w-56),28)
        self.edge_hint.setGeometry(0,max(0,h-44),w,28)
        self.capture_toast.setGeometry(max(20,(w-500)//2),max(90,h-170),min(500,w-40),104)
        for panel in (self.top_bar,self.left_panel,self.right_panel,self.log_panel,self.status_label,self.edge_hint,self.capture_toast):
            panel.raise_()

    def toggle_connection_panel(self):
        self.left_panel.setVisible(not self.left_panel.isVisible())
        self.left_panel.raise_()

    def toggle_control_panel(self):
        self.right_panel.setVisible(not self.right_panel.isVisible())
        self.right_panel.raise_()

    def toggle_log_panel(self):
        self.log_panel.setVisible(not self.log_panel.isVisible())
        self.log_panel.raise_()

    def eventFilter(self, source, event):
        if self._focus_mode and not self._closing and source is self.surface and event.type()==QEvent.Type.Leave:
            self._edge_hide_timer.start(250)
        if self._focus_mode and not self._closing and event.type() == QEvent.Type.MouseMove:
            if isinstance(source,QWidget) and (source is self.surface or self.surface.isAncestorOf(source)):
                point = self.surface.mapFromGlobal(event.globalPosition().toPoint())
                self.update_edge_panels(point)
        if source is self and event.type() == QEvent.Type.WindowStateChange:
            if self._focus_mode and not self.isFullScreen():
                self.set_focus_mode(False)
        return super().eventFilter(source,event)

    def update_edge_panels(self, point):
        self._last_pointer = point
        w,h=self.surface.width(),self.surface.height()
        desired=[]
        for panel,at_edge in ((self.left_panel,point.x()<=20),
                              (self.top_bar,point.y()<=20),
                              (self.right_panel,point.x()>=w-21)):
            inside=panel.isVisible() and panel.geometry().adjusted(-8,-8,8,8).contains(point)
            if at_edge or inside:
                desired.append(panel)
        if desired:
            self._edge_hide_timer.stop()
            for panel in (self.left_panel,self.top_bar,self.right_panel):
                panel.setVisible(panel in desired)
                if panel in desired:panel.raise_()
        else:
            # Grace period lets the pointer cross the gap into a panel.
            if not self._edge_hide_timer.isActive():self._edge_hide_timer.start(250)

    def hide_edge_panels(self):
        if self._focus_mode:
            for panel in (self.left_panel,self.top_bar,self.right_panel):panel.hide()

    def set_focus_mode(self, enabled):
        self._focus_mode=enabled
        self._edge_hide_timer.stop()
        self.top_bar.setVisible(not enabled)
        self.left_panel.hide()
        self.right_panel.hide()
        self.log_panel.hide()
        self.status_label.setVisible(not enabled)
        self.fullscreen_button.setText(tr('Pencereye dön  ↙') if enabled else tr('Tam ekran  ↗'))
        if enabled:
            self.edge_hint.show()
            QTimer.singleShot(3000,self.edge_hint.hide)
        else:
            self.edge_hint.hide()

    def log(self, message):
        message=redact(message,secrets=(self._password,self._ssid,self.connection_profile.get('device_name','')))
        self._log_lines.append(f'[{datetime.now():%H:%M:%S}] {message}')
        self.log_view.appendPlainText(self._log_lines[-1])

    def show_status(self, message):
        if not self._closing:
            self.status_label.setText(message)
            if 'capture' in self._pending:
                self.capture_progress_label.setText(message)
            self.log(message)

    def update_controls(self):
        if self._closing:
            self.centralWidget().setEnabled(False)
            return
        ble_running = bool(self.bluetooth_worker and self.bluetooth_worker.isRunning()) or bool(self.connection_worker and self.connection_worker.isRunning())
        wifi_running = bool(self.wifi_worker and self.wifi_worker.isRunning())
        self.scan_button.setEnabled(not self.demo and not ble_running and not self._connected)
        self.prepare_button.setEnabled(not self.demo and not ble_running and not self._connected and self.device_combo.count() > 0)
        self.wifi_button.setEnabled(not self.demo and bool(self._ssid) and not wifi_running and not self._connected)
        self.connect_button.setEnabled(not self.demo and not self._connected and not self._quick_connecting and 'connect' not in self._pending and not wifi_running)
        self.address.setEnabled(not self._connected and not self._pending)
        self.port.setEnabled(not self._connected and not self._pending)
        running = bool(self.stream_thread and self.stream_thread.isRunning())
        self.start_button.setEnabled(self._connected and not running and not self._pending)
        self.stop_button.setEnabled(self._connected and (running or self._preview_state in ('waiting', 'active', 'stalled')) and not self._pending)
        self.record_button.setEnabled(self._connected and self._recording is not None and not self._pending)
        self.record_button.setText(tr('SD Kaydını Durdur') if self._recording else tr('SD Kaydını Başlat'))
        can_capture=self._connected and self._recording is False and not self._pending and not self.demo
        self.quality_video_button.setEnabled(can_capture)
        self.quality_photo_button.setEnabled(can_capture)

    def capture_quality(self,kind):
        if self.demo or not self._connected:
            self.show_status(tr('Kaliteli kadraj için gerçek kameraya bağlanın.'))
            return
        if self._recording is not False or self._pending:
            self.show_status(tr('Kadraj kontrolünü kayıt başlamadan önce kullanın.'))
            return
        self._pending.add('capture')
        self.capture_progress_label.setText(tr('Orijinal kamera görseli hazırlanıyor…'))
        self.capture_toast.show()
        self.capture_toast.raise_()
        self.gopro.capture_quality(kind)
        self.update_controls()

    def save_connection_profile(self,*args):
        if self.demo or self._closing or self._saving_connection:return
        self._saving_connection=True
        try:
            remember=self.remember_camera.isChecked()
            self.auto_connect.setEnabled(remember)
            if not remember:self.auto_connect.setChecked(False)
            profile=dict(self.connection_profile)
            profile.update(remember=remember,auto_connect=self.auto_connect.isChecked(),port=self.port.value(),language=language())
            profile['address']=self.address.text()
            if self._ssid:profile['ssid']=self._ssid
            device=self.device_combo.currentData()
            if device:
                profile['device']=device
                profile['device_name']=self.device_combo.currentText()
            self.connection_profile=self.connection_store.save(profile)
        except OSError:
            self.show_status(tr('Kamera tercihi kaydedilemedi; mevcut bağlantı kullanılabilir.'))
        finally:self._saving_connection=False

    def quick_connect(self,force_ble=False):
        if self.demo or self._closing or self._pending or self._quick_connecting:return
        if self._connected and not force_ble:return
        if self.connection_worker and self.connection_worker.isRunning():return
        self.save_connection_profile()
        self._quick_connecting=True
        self._auto_start_on_connect=False
        worker=QuickConnectionWorker(self.connection_profile,self,force_ble=force_ble)
        self.connection_worker=worker
        self._workers.append(worker)
        worker.status.connect(self.show_status)
        worker.error.connect(self.on_quick_connection_error)
        worker.profile_ready.connect(self.on_connection_profile_ready)
        worker.ready.connect(self.on_quick_connection_ready)
        worker.finished.connect(lambda worker=worker:self.worker_finished(worker))
        worker.start()
        self.update_controls()

    def on_connection_profile_ready(self,profile):
        if self._closing:return
        if profile.get('ssid'):
            self._ssid=profile['ssid']
            self.ssid_label.setText(tr('Kayıtlı kamera ağı: ')+self._ssid)
        if profile.get('device'):
            index=self.device_combo.findData(profile['device'])
            if index<0:
                self.device_combo.addItem(profile.get('device_name') or 'GoPro',profile['device'])
                index=self.device_combo.count()-1
            self.device_combo.setCurrentIndex(index)
        self.save_connection_profile()

    def on_quick_connection_ready(self,result):
        if self._closing:return
        self._transport=result['transport']
        self.address.setText(result['address'])
        self._auto_start_on_connect=True
        self.connect_camera()

    def on_quick_connection_error(self,message):
        if self._closing:return
        self._quick_connecting=False
        self._auto_start_on_connect=False
        self.setup_toggle.setChecked(True)
        self.left_panel.show()
        self.show_status(message)
        self.update_controls()

    def on_quality_ready(self,capture):
        if self._closing:
            capture.pop('frame',None)
            return
        try:
            for previous in list(self._reviews):previous.close()
            review=QualityReview(capture,self)
            self._reviews.append(review)
            review.discarded.connect(lambda review=review:self.on_review_closed(review))
            review.show()
            review.raise_()
            review.activateWindow()
        except (ValueError,OSError) as exc:
            self.show_status(tr('Geçici görsel açılamadı: {0}').format(exc))
        finally:
            # The viewer owns a Qt pixel copy; no frame is kept for reopening.
            capture.pop('frame',None)

    def on_review_closed(self,review):
        if review in self._reviews:self._reviews.remove(review)
        if self._closing:return
        self.raise_()
        self.activateWindow()
        self.request_return_to_live()

    def request_return_to_live(self):
        if self._closing or self.demo or not self._connected:return
        self._return_to_live=True
        self._live_resume_attempts=0
        self._live_return_timer.start()

    def check_return_to_live(self):
        if self._closing or not self._connected or not self._return_to_live:
            self._return_to_live=False
            self._live_return_timer.stop()
            return
        now=time.monotonic()
        running=bool(self.stream_thread and self.stream_thread.isRunning())
        if running and self._preview_state=='active' and self._frame is not None and now-self._last_frame_time<2:
            self._return_to_live=False
            self._live_return_timer.stop()
            return
        if self._pending or now-self._live_restart_at<5:return
        if self._live_resume_attempts>=2:
            self._return_to_live=False
            self._live_return_timer.stop()
            if self._transport=='Wi-Fi' and not (self.connection_worker and self.connection_worker.maintaining_ble) and not (self.bluetooth_worker and self.bluetooth_worker.isRunning()):
                self.quick_connect(force_ble=True)
                return
            self.show_status(tr('Canlıya dönüşte görüntü alınamadı. Kamera Wi-Fi bağlantısını kontrol edin.'))
            return
        self._live_resume_attempts+=1
        self._live_restart_at=now
        self.show_status(tr('Canlı önizlemeye dönülüyor…'))
        self.stop_decoder()
        self.start_stream()

    def scan_bluetooth(self):
        self.device_combo.clear()
        self.bluetooth_worker = BluetoothWorker(parent=self)
        self._start_ble_worker()
        self.bluetooth_worker.devices_found.connect(self.on_devices)
        self.bluetooth_worker.start()
        self.update_controls()

    def _start_ble_worker(self):
        worker = self.bluetooth_worker
        self._workers.append(worker)
        worker.status.connect(self.show_status)
        worker.error.connect(self.show_status)
        worker.finished.connect(lambda worker=worker: self.worker_finished(worker))

    def worker_finished(self, worker):
        queued=None
        if worker is self.stream_thread:
            self.stream_thread = None
            queued,self._queued_stream_url=self._queued_stream_url,None
        if worker is self.bluetooth_worker:
            self.bluetooth_worker = None
        if worker is self.wifi_worker:
            self.wifi_worker = None
        if worker is self.connection_worker:
            self.connection_worker=None
            self._quick_connecting=False
        if worker in self._workers:
            self._workers.remove(worker)
        worker.deleteLater()
        self.update_controls()
        if queued and not self._closing:
            self.on_stream_url_ready(queued)

    def on_devices(self, devices):
        for name, address in devices:
            self.device_combo.addItem(f'{name} ({address})', address)
        self.show_status(tr('{0} GoPro bulundu.').format(len(devices)) if devices else tr('GoPro bulunamadı. Kamerada eşleştirme ekranını açıp yeniden arayın.'))
        self.update_controls()

    def prepare_wifi(self):
        device = self.device_combo.currentData()
        if not device:
            return
        self.bluetooth_worker = BluetoothWorker(device, self)
        self._start_ble_worker()
        self.bluetooth_worker.wifi_ready.connect(self.on_wifi_ready)
        self.bluetooth_worker.start()
        self.update_controls()

    def on_wifi_ready(self, ssid, password):
        self._ssid, self._password = ssid, password
        self.ssid_label.setText(tr('Kamera ağı: ') + ssid)
        self.save_connection_profile()
        self.update_controls()

    def connect_wifi(self):
        self.wifi_worker = WifiConnectWorker(self._ssid, self._password, self)
        # empty credential default / reference release, not a secret.
        self._password=''  # nosec B105
        self._workers.append(self.wifi_worker)
        self.wifi_worker.completed.connect(lambda ok, message: self.show_status(message))
        self.wifi_worker.finished.connect(lambda worker=self.wifi_worker: self.worker_finished(worker))
        self.wifi_worker.start()
        self.show_status(tr('Windows kamera Wi-Fi ağına bağlanıyor…'))
        self.update_controls()

    def connect_camera(self):
        if self._closing or 'connect' in self._pending:return
        try:
            address = validate_address(self.address.text())
        except CameraError as exc:
            self.show_status(str(exc))
            return
        self._pending.add('connect')
        self.gopro.connect_camera(address, self.port.value())
        self.update_controls()

    def on_connected(self, connected):
        self._connected = connected
        if connected:
            self.setup_toggle.setChecked(False)
            self.left_panel.hide()
            self.save_connection_profile()
            if self._auto_start_on_connect:
                self._quick_connecting=False
                self._auto_start_on_connect=False
                self.request_return_to_live()
        if not connected:
            self._recording = None
            self.record_badge.setText(tr('SD KAYDI: DURUM BİLİNMİYOR'))
            self.stop_decoder()
        self.update_controls()

    def on_info(self, info):
        self.camera_label.setText(tr('{0} · {1}\nFirmware: {2}').format(info["model_name"], self._transport, info.get("firmware_version", "—")))

    def on_camera_state(self, state):
        self._recording = bool(state['10'])
        duration = int(state.get('13', 0))
        self.record_badge.setText(tr('● SD KAYDI: {0:02}:{1:02}').format(duration // 60, duration % 60) if self._recording else tr('SD KAYDI: DURDU'))
        self.record_badge.setStyleSheet('color: #ff6b6b;' if self._recording else 'color: #a6b5c6;')
        storage = {0: tr('Hazır'), 1: tr('Dolu'), 2: tr('Kart yok'), 3: tr('Format hatası'), 4: tr('Meşgul'), 8: tr('Kart değişti')}.get(state.get('33'), tr('Bilinmiyor'))
        self.telemetry.setText(tr('Pil: %{0}   SD: {1}').format(state.get("70", "—"), storage))
        self.update_controls()

    def start_stream(self):
        self._pending.add('start')
        self.gopro.start_stream()
        self.update_controls()

    def on_stream_url_ready(self, url):
        if self._closing:
            return
        if self.stream_thread and self.stream_thread.isRunning():
            self._queued_stream_url=url
            self.stream_thread.stop()
            return
        self.stream_thread = VideoStreamThread(url, self, camera_host=urlsplit(validate_address(self.address.text())).hostname)
        self._workers.append(self.stream_thread)
        self.stream_thread.status_signal.connect(self.show_status)
        self.stream_thread.debug_signal.connect(self.log)
        self.stream_thread.stream_state.connect(self.on_preview_state)
        self.stream_thread.receiver_ready.connect(self.gopro.decoder_ready)
        self.stream_thread.metrics.connect(self.on_video_metrics)
        self.stream_thread.finished.connect(lambda worker=self.stream_thread: self.worker_finished(worker))
        self.stream_thread.start()
        self.update_controls()

    def on_video_metrics(self, metrics):
        self.source_label.setText(tr('{0} × {1}  ·  {2:.0f} fps\nDüşük gecikme').format(metrics["width"], metrics["height"], metrics["fps"]))

    def stop_stream(self):
        self._return_to_live=False
        self._live_return_timer.stop()
        self.stop_decoder()
        self._pending.add('stop')
        self.gopro.stop_stream()
        self.update_controls()

    def stop_decoder(self):
        self._queued_stream_url=None
        if self.stream_thread:
            self.stream_thread.stop()
        self._frame = None
        self._last_frame_time = 0
        self.video_label.clear()
        self.video_label.setText(tr('Önizleme durdu. SD kaydı ayrı olarak sürüyor olabilir.'))
        self.on_preview_state('stopped')

    def on_preview_state(self, state):
        self._preview_state = state
        text = {'waiting': tr('GÖRÜNTÜ BEKLENİYOR'), 'active': tr('● CANLI'), 'stalled': tr('GÖRÜNTÜ KESİLDİ'), 'failed': tr('GÖRÜNTÜ YOK'), 'stopped': tr('ÖNİZLEME DURDU')}
        self.preview_badge.setText(text.get(state, state))
        self.preview_badge.setStyleSheet('color: #62d6a0;' if state == 'active' else 'color: #ffcb72;')
        if state != 'active':
            self._frame = None
            self.video_label.clear()
            self.video_label.setText(text.get(state, state) + tr('\nSD kayıt durumunu yukarıdan kontrol edin.'))
        self.update_controls()

    def toggle_recording(self):
        if self._recording is None:
            return
        self._pending.add('record')
        self.gopro.set_recording(not self._recording)
        self.update_controls()

    def on_command_finished(self, command, ok):
        self._pending.discard(command)
        if command=='connect' and not ok:
            self._quick_connecting=False
            self._auto_start_on_connect=False
        if command == 'start' and not ok:
            self.stop_decoder()
        if command == 'capture':
            self.capture_toast.hide()
        self.update_controls()

    def render_frame(self):
        if self._closing:
            return
        if self.demo:
            self._demo_tick += 1
            frame = np.zeros((720, 1280, 3), np.uint8)
            frame[:] = (35, 25, 18)
            for x in range(0, 1280, 80):
                cv2.line(frame, (x, 0), (x, 720), (62, 48, 36), 1)
            for y in range(0, 720, 80):
                cv2.line(frame, (0, y), (1280, y), (62, 48, 36), 1)
            cv2.circle(frame, (150 + (self._demo_tick * 4) % 980, 360), 65, (110, 200, 70), -1)
            cv2.putText(frame, 'GOPRO LITHERO LIVE MONITOR - SYNTHETIC PREVIEW' if language()=='en' else 'GOPRO LITHERO LIVE MONITOR - SENTETIK GORUNTU', (80, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (230, 230, 230), 2)
            cv2.putText(frame, datetime.now().strftime('%H:%M:%S'), (80, 630), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (230, 230, 230), 2)
        elif self.stream_thread:
            frame = self.stream_thread.take_frame()
        else:
            return
        if frame is not None:
            if not self.demo and self._preview_state == 'stopped':
                return
            if not self.demo and self._preview_state != 'active':
                self.on_preview_state('active')
            self._frame = frame
            self._last_frame_time = time.monotonic()
            self.display_frame()
        elif not self.demo and self._preview_state == 'active' and time.monotonic() - self._last_frame_time > 2:
            self.on_preview_state('stalled')

    def display_frame(self):
        if self._frame is None:
            return
        self.video_label.mirrored=self.mirror.isChecked()
        self.video_label.fill=self.fill_toggle.isChecked()
        self.video_label.set_frame(self._frame)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_frame'):
            self.layout_overlays()

    def toggle_fullscreen(self):
        if self._focus_mode:
            self.showNormal()
            self.set_focus_mode(False)
        else:
            self.set_focus_mode(True)
            self.showFullScreen()
        self.layout_overlays()

    def escape(self):
        if self._focus_mode:
            self.toggle_fullscreen()
        else:
            self.left_panel.hide()
            self.right_panel.hide()
            self.log_panel.hide()

    def closeEvent(self, event):
        if self._closing and not self.gopro.isRunning() and not any(w.isRunning() for w in self._workers):
            event.accept()
            return
        event.ignore()
        if not self._closing:
            self._closing = True
            QApplication.instance().removeEventFilter(self)
            self._edge_hide_timer.stop()
            for review in list(self._reviews):review.close()
            self._close_started = time.monotonic()
            self.render_timer.stop()
            self._live_return_timer.stop()
            self.status_label.setText(tr('Bağlantılar kapatılıyor… SD kaydı kamerada devam edebilir.'))
            self.stop_decoder()
            self.gopro.shutdown()
            for worker in self._workers:
                if isinstance(worker, (BluetoothWorker,QuickConnectionWorker)):
                    worker.stop()
                else:
                    worker.requestInterruption()
            # empty credential default / reference release, not a secret.
            self._password = ''  # nosec B105
            self.password_field.clear()
            self.update_controls()
            self.close_timer.start(100)

    def finish_close(self):
        if not self.gopro.isRunning() and not any(w.isRunning() for w in self._workers):
            self.close_timer.stop()
            self.close()
        elif time.monotonic() - self._close_started > 10:
            self.status_label.setText(tr('Süren bağlantı işlemi bekleniyor… Kamera SD kaydı etkilenmez.'))

def main():
    parser = argparse.ArgumentParser(description=tr('GoPro LIT HERO bilgisayardan izleme'))
    parser.add_argument('--demo', action='store_true', help=tr('Kamerasız sentetik görüntü'))
    parser.add_argument('--language',choices=('en','tr'),help='Interface language; English is the first-launch default')
    parser.add_argument('--connect', action='store_true', help=tr('Hatırlanan Wi-Fi bağlantısıyla otomatik önizlemeyi aç'))
    parser.add_argument('--no-auto-connect',action='store_true',help=tr('Bu açılışta otomatik bağlantıyı atla'))
    parser.add_argument('--fullscreen', action='store_true', help=tr('Yalnızca görüntüyle tam ekran aç'))
    parser.add_argument('--debug',action='store_true',help=tr('Bağlantı durumunu terminale yazdır'))
    parser.add_argument('--smoke-test', action='store_true', help=tr('Arayüzü aç, doğrula ve kapat'))
    parser.add_argument('--screenshot', type=Path, help=tr('Smoke test sırasında pencere görüntüsü kaydet'))
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    window = MainWindow(demo=args.demo,ui_language=args.language)
    window.show()
    if args.fullscreen:
        window.toggle_fullscreen()
    if args.debug and sys.stdout is not None:
        if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf8',errors='replace')
        window.gopro.connection_status.connect(lambda message:print(message,flush=True))
    if not args.demo and not args.smoke_test and not args.no_auto_connect and (args.connect or window.connection_profile['auto_connect']):
        QTimer.singleShot(100, window.quick_connect)
    if args.smoke_test:
        def finish():
            window.edge_hint.hide()
            if args.screenshot:
                window.grab().save(str(args.screenshot))
            window.close()
        QTimer.singleShot(1500, finish)
    return app.exec()

if __name__ == '__main__':
    sys.exit(main())
