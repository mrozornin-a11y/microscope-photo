"""Оформление: палитра и таблица стилей."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from ..resources import resource_path

ACCENT = "#2563eb"
ACCENT_HOVER = "#1d4ed8"
ACCENT_SOFT = "#e0e9ff"
BG = "#f4f5f7"
PANEL = "#ffffff"
BORDER = "#e3e5e9"
TEXT = "#1f2328"
MUTED = "#6b7280"
SUCCESS = "#15803d"
WARNING = "#b45309"
ERROR = "#b91c1c"
VIEWER_BG = "#1b1c1f"
ARROW_DOWN = resource_path("arrow_down.svg")
ARROW_UP = resource_path("arrow_up.svg")

STYLE = f"""
QWidget {{
    color: {TEXT};
    font-size: 10pt;
}}
QMainWindow, #Workspace, #StartPage {{
    background: {BG};
}}
#SidePanel {{
    background: {PANEL};
    border-left: 1px solid {BORDER};
}}
#ListPanel {{
    background: {PANEL};
    border-right: 1px solid {BORDER};
}}
#TopBar, #NavBar {{
    background: {PANEL};
    border-bottom: 1px solid {BORDER};
}}
#NavBar {{
    border-bottom: none;
    border-top: 1px solid {BORDER};
}}
QLabel#SectionTitle {{
    color: {MUTED};
    font-size: 9pt;
    font-weight: 600;
    letter-spacing: 0.5px;
    margin-top: 6px;
}}
QLabel#Muted, QLabel#Hint {{
    color: {MUTED};
}}
QLabel#Hint {{
    font-size: 9pt;
}}
QLabel#BigTitle {{
    font-size: 20pt;
    font-weight: 600;
}}
QLabel#Counter {{
    font-size: 11pt;
    color: {MUTED};
}}
QLabel#OutputName {{
    color: {TEXT};
    background: {BG};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 8px;
    font-family: "Consolas", "Cascadia Mono", monospace;
}}

QPushButton {{
    background: {PANEL};
    border: 1px solid #cfd3da;
    border-radius: 6px;
    padding: 6px 14px;
    min-height: 20px;
}}
QPushButton:hover {{
    background: #f0f2f5;
    border-color: #b8bec8;
}}
QPushButton:pressed {{
    background: #e6e9ee;
}}
QPushButton:disabled {{
    color: #a6abb3;
    background: #f7f8f9;
    border-color: {BORDER};
}}
QPushButton#Primary {{
    background: {ACCENT};
    color: white;
    border: 1px solid {ACCENT};
    font-weight: 600;
    padding: 8px 18px;
}}
QPushButton#Primary:hover {{
    background: {ACCENT_HOVER};
}}
QPushButton#Primary:disabled {{
    background: #9db5ef;
    border-color: #9db5ef;
}}
QPushButton#Huge {{
    background: {ACCENT};
    color: white;
    border: none;
    border-radius: 10px;
    font-size: 15pt;
    font-weight: 600;
    padding: 18px 40px;
}}
QPushButton#Huge:hover {{
    background: {ACCENT_HOVER};
}}
QPushButton#Link, QToolButton#Link {{
    background: transparent;
    border: none;
    color: {ACCENT};
    padding: 4px 2px;
    text-align: left;
}}
QPushButton#Link:hover, QToolButton#Link:hover {{
    text-decoration: underline;
}}
QPushButton#Toggle {{
    padding: 8px 10px;
    text-align: center;
}}
QPushButton#Toggle:checked {{
    background: {ACCENT_SOFT};
    border: 2px solid {ACCENT};
    color: {ACCENT_HOVER};
    font-weight: 600;
    padding: 7px 9px;
}}
QPushButton#NumButton, QPushButton#NumTile {{
    padding: 4px 0px;
    min-height: 22px;
}}
QPushButton#NumButton:checked {{
    background: {ACCENT_SOFT};
    border: 2px solid {ACCENT};
    color: {ACCENT_HOVER};
    font-weight: 600;
    padding: 3px 0px;
}}
QPushButton#NumTile {{
    color: {ACCENT};
    border-style: dashed;
}}
QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 4px 8px;
}}
QToolButton:hover {{
    background: #eef0f3;
    border-color: {BORDER};
}}
QToolButton:disabled {{
    color: #b5b9c0;
}}

QPushButton#Step {{
    background: transparent;
    border: none;
    border-radius: 14px;
    padding: 6px 14px;
    color: {MUTED};
    font-weight: 600;
}}
QPushButton#Step:hover {{
    background: #eef0f3;
}}
QPushButton#Step:checked {{
    background: {ACCENT};
    color: white;
}}
QLabel#StepArrow {{
    color: #b8bec8;
}}

QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
    background: white;
    border: 1px solid #cfd3da;
    border-radius: 6px;
    padding: 5px 8px;
    min-height: 22px;
    selection-background-color: {ACCENT};
}}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {{
    border: 2px solid {ACCENT};
    padding: 4px 7px;
}}
QComboBox::drop-down {{
    border: none;
    width: 28px;
}}
QComboBox::down-arrow {{
    image: url("{ARROW_DOWN}");
    width: 12px;
    height: 8px;
}}
QComboBox QAbstractItemView {{
    border: 1px solid {BORDER};
    background: white;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT};
    padding: 2px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 24px;
    border: none;
    border-left: 1px solid {BORDER};
    border-top-right-radius: 6px;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 24px;
    border: none;
    border-left: 1px solid {BORDER};
    border-bottom-right-radius: 6px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
    background: #eef0f3;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url("{ARROW_UP}");
    width: 10px;
    height: 7px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url("{ARROW_DOWN}");
    width: 10px;
    height: 7px;
}}
QComboBox#BigCombo, QSpinBox#BigSpin {{
    font-size: 12pt;
}}

QListView#PhotoList {{
    background: {PANEL};
    border: none;
    outline: none;
}}
QProgressBar {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    background: {BG};
    text-align: center;
    min-height: 16px;
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 5px;
}}
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 14px;
    padding: 12px 10px 10px 10px;
    background: {PANEL};
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {TEXT};
}}
QTableWidget {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    gridline-color: {BORDER};
    background: white;
}}
QHeaderView::section {{
    background: {BG};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 4px 6px;
    color: {MUTED};
    font-weight: 600;
}}
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    background: {PANEL};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    padding: 7px 16px;
    border: none;
    color: {MUTED};
    font-weight: 600;
}}
QTabBar::tab:selected {{
    color: {ACCENT};
    border-bottom: 2px solid {ACCENT};
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QFrame#Card {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame#Warning {{
    background: #fff7e6;
    border: 1px solid #f3d19c;
    border-radius: 8px;
}}
QMenu {{
    background: white;
    border: 1px solid {BORDER};
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 22px 6px 14px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background: {ACCENT_SOFT};
    color: {TEXT};
}}
QToolTip {{
    background: #2b2d31;
    color: white;
    border: none;
    padding: 5px 8px;
}}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(BG))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Base, QColor("white"))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(BG))
    pal.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Button, QColor(PANEL))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("white"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor("#2b2d31"))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor("white"))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(MUTED))
    app.setPalette(pal)
    app.setStyleSheet(STYLE)
