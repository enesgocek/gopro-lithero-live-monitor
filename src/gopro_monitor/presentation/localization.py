"""Qt widget translation; camera identifiers can opt out."""
from gopro_monitor.shared.i18n import translated_text

def retranslate_widgets(root, previous,skip_text=()):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QWidget, QLabel, QPushButton, QCheckBox, QGroupBox, QLineEdit
    for widget in [root, *root.findChildren(QWidget)]:
        if isinstance(widget, (QLabel, QPushButton, QCheckBox)) and widget not in skip_text:
            widget.setText(translated_text(widget.text(), previous))
        if isinstance(widget, QLabel):
            widget.setTextFormat(Qt.TextFormat.PlainText)
        if isinstance(widget, QGroupBox):
            widget.setTitle(translated_text(widget.title(), previous))
        if isinstance(widget, QLineEdit):
            widget.setPlaceholderText(translated_text(widget.placeholderText(), previous))
        widget.setToolTip(translated_text(widget.toolTip(), previous))
        widget.setWindowTitle(translated_text(widget.windowTitle(), previous))
        if hasattr(widget, 'message'):
            widget.setText(translated_text(widget.message, previous))
