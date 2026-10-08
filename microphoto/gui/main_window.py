"""Главное окно: стартовый экран и рабочее пространство из трех этапов."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QKeyCombination, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from .. import APP_TITLE
from ..core import cache, project_ops, state
from .app_settings import AppSettings
from .controller import ProjectController
from .crop_page import CropPage
from .final_page import FinalPage
from .settings_dialog import SettingsDialog
from .dialogs import ask_continue
from .media import MediaService
from .photo_page import PhotoPage
from .start_page import StartPage
from .widgets.photo_list import PhotoListView
from .widgets.toggles import StepBar

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.app_settings = AppSettings()
        self.ctrl = ProjectController(self.app_settings, self)
        self.media = MediaService(self.ctrl, self)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.start_page = StartPage()
        self.start_page.chooseFolder.connect(self.choose_folder)
        self.start_page.openRecent.connect(self._open_recent)
        self.stack.addWidget(self.start_page)

        self.workspace = QWidget()
        self.workspace.setObjectName("Workspace")
        self.stack.addWidget(self.workspace)
        ws = QVBoxLayout(self.workspace)
        ws.setContentsMargins(0, 0, 0, 0)
        ws.setSpacing(0)
        ws.addWidget(self._build_top_bar())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        list_panel = QFrame()
        list_panel.setObjectName("ListPanel")
        list_panel.setFixedWidth(268)
        lp = QVBoxLayout(list_panel)
        lp.setContentsMargins(0, 6, 0, 6)
        self.photo_list = PhotoListView(self.ctrl, self.media)
        self.photo_list.photoActivated.connect(self.goto_photo)
        self.photo_list.removeRequested.connect(self.remove_photos)
        lp.addWidget(self.photo_list)
        self.remove_btn = QPushButton("Удалить из списка")
        self.remove_btn.setObjectName("Link")
        self.remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.remove_btn.setToolTip("Убрать выбранные фото из этой партии (Delete).\n"
                                   "Файлы на диске не удаляются. Вернуть — Ctrl+Z.\n"
                                   "Несколько фото — Ctrl или Shift + щелчок.")
        self.remove_btn.clicked.connect(lambda: self.remove_photos(self.photo_list.selected_rows()))
        rm_row = QHBoxLayout()
        rm_row.setContentsMargins(14, 0, 0, 0)
        rm_row.addWidget(self.remove_btn)
        rm_row.addStretch(1)
        lp.addLayout(rm_row)
        body.addWidget(list_panel)

        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        ws.addLayout(body, 1)
        ws.addWidget(self._build_nav_bar())

        self.photo_page = PhotoPage(self.ctrl, self.media)
        self.photo_page.finished.connect(lambda: self.set_stage(1, jump_unconfirmed=True))
        self.page_list: list[QWidget] = [self.photo_page]
        self._add_more_pages()
        for p in self.page_list:
            self.pages.addWidget(p)

        self._build_shortcuts()
        self.statusBar().setSizeGripEnabled(False)

        self.ctrl.currentChanged.connect(lambda _i: self._update_nav())
        self.ctrl.photoListChanged.connect(self._update_nav)
        self.ctrl.photoChanged.connect(lambda _i: self._update_nav())
        self.ctrl.projectLoaded.connect(self._on_project_loaded)

        geo = self.app_settings.geometry()
        if geo is None or not self.restoreGeometry(geo):
            self.resize(1400, 900)
        QTimer.singleShot(0, self._startup)

    def _add_more_pages(self) -> None:
        """Страницы этапов 2 и 3."""
        self.crop_page = CropPage(self.ctrl, self.media)
        self.crop_page.finished.connect(lambda: self.set_stage(2))
        self.page_list.append(self.crop_page)
        self.final_page = FinalPage(self.ctrl, self.media)
        self.final_page.openSettings.connect(lambda: self.open_settings(0))
        self.final_page.gotoPhoto.connect(self._goto_photo_stage)
        self.final_page.startOver.connect(self.start_over)
        self.final_page.busyChanged.connect(self._set_busy)
        self.page_list.append(self.final_page)

    # ------------------------------------------------------------ построение
    def _build_top_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("TopBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 8, 12, 8)
        self.step_bar = StepBar()
        self.step_bar.stepClicked.connect(lambda i: self.set_stage(i))
        lay.addWidget(self.step_bar)
        lay.addStretch(1)

        self.folder_btn = QToolButton()
        self.folder_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.folder_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        menu = QMenu(self.folder_btn)
        menu.addAction("Открыть исходную папку", self._open_source_folder)
        menu.addAction("Выбрать другую папку…", self.choose_folder)
        menu.addSeparator()
        menu.addAction("Начать заново…", self.start_over)
        self.folder_btn.setMenu(menu)
        lay.addWidget(self.folder_btn)
        lay.addSpacing(10)

        self.undo_btn = QToolButton()
        self.undo_btn.setText("↶")
        self.redo_btn = QToolButton()
        self.redo_btn.setText("↷")
        for b in (self.undo_btn, self.redo_btn):
            b.setStyleSheet("font-size: 15pt; padding: 0px 8px;")
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.undo_btn.clicked.connect(self.ctrl.undo_stack.undo)
        self.redo_btn.clicked.connect(self.ctrl.undo_stack.redo)
        us = self.ctrl.undo_stack
        us.canUndoChanged.connect(self.undo_btn.setEnabled)
        us.canRedoChanged.connect(self.redo_btn.setEnabled)
        us.undoTextChanged.connect(lambda t: self.undo_btn.setToolTip(f"Отменить: {t} (Ctrl+Z)" if t else "Отменить (Ctrl+Z)"))
        us.redoTextChanged.connect(lambda t: self.redo_btn.setToolTip(f"Повторить: {t} (Ctrl+Y)" if t else "Повторить (Ctrl+Y)"))
        self.undo_btn.setEnabled(False)
        self.redo_btn.setEnabled(False)
        self.undo_btn.setToolTip("Отменить (Ctrl+Z)")
        self.redo_btn.setToolTip("Повторить (Ctrl+Y)")
        lay.addWidget(self.undo_btn)
        lay.addWidget(self.redo_btn)
        lay.addSpacing(6)

        self.settings_btn = QPushButton("⚙ Настройки")
        self.settings_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.settings_btn.clicked.connect(lambda: self.open_settings(0))
        lay.addWidget(self.settings_btn)
        return bar

    def _build_nav_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("NavBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 8, 14, 8)
        self.prev_btn = QPushButton("← Назад")
        self.prev_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.prev_btn.setMinimumWidth(120)
        self.prev_btn.clicked.connect(self.go_prev)
        self.counter = QLabel()
        self.counter.setObjectName("Counter")
        self.counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next_btn = QPushButton("Далее →")
        self.next_btn.setObjectName("Primary")
        self.next_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.next_btn.setMinimumWidth(170)
        self.next_btn.clicked.connect(self.go_accept)
        lay.addWidget(self.prev_btn)
        lay.addStretch(1)
        lay.addWidget(self.counter)
        lay.addStretch(1)
        lay.addWidget(self.next_btn)
        return bar

    def _build_shortcuts(self) -> None:
        def sc(seq, fn):
            s = QShortcut(QKeySequence(seq), self)
            s.setContext(Qt.ShortcutContext.WindowShortcut)
            s.activated.connect(fn)
            return s

        sc(Qt.Key.Key_Return, self.go_accept)
        sc(Qt.Key.Key_Enter, self.go_accept)
        sc(Qt.Key.Key_Left, self.go_prev)
        sc(Qt.Key.Key_Right, self.go_next)
        sc(Qt.Key.Key_Delete, lambda: self.remove_photos(self.photo_list.selected_rows()))
        for n in range(1, 5):
            sc(getattr(Qt.Key, f"Key_{n}"), lambda n=n: self._digit(n))
        undo = QAction("Отменить", self)
        undo.setShortcuts([QKeySequence.StandardKey.Undo])
        undo.triggered.connect(self._undo)
        redo = QAction("Повторить", self)
        redo.setShortcuts([QKeySequence(QKeyCombination(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Y)),
                           QKeySequence(QKeyCombination(Qt.KeyboardModifier.ControlModifier
                                                        | Qt.KeyboardModifier.ShiftModifier, Qt.Key.Key_Z))])
        redo.triggered.connect(self._redo)
        self.addAction(undo)
        self.addAction(redo)

    # ------------------------------------------------------------ состояние
    def _in_workspace(self) -> bool:
        return self.stack.currentWidget() is self.workspace and self.ctrl.has_project()

    def current_page(self):
        return self.pages.currentWidget()

    def _commit_page(self) -> None:
        page = self.current_page()
        if hasattr(page, "commit_pending"):
            page.commit_pending()

    def _undo(self) -> None:
        if self._in_workspace() and not self.final_page.is_busy():
            self._commit_page()
            self.ctrl.undo_stack.undo()

    def _redo(self) -> None:
        if self._in_workspace() and not self.final_page.is_busy():
            self.ctrl.undo_stack.redo()

    def _digit(self, n: int) -> None:
        if self._in_workspace() and self.current_page() is self.photo_page:
            self.photo_page.set_magnification_by_number(n)

    def go_accept(self) -> None:
        if self._in_workspace():
            self.current_page().accept()
            self._update_nav()

    def go_next(self) -> None:
        if self._in_workspace():
            self.current_page().go_next()
            self._update_nav()

    def go_prev(self) -> None:
        if self._in_workspace():
            self.current_page().go_prev()
            self._update_nav()

    def goto_photo(self, index: int) -> None:
        self._commit_page()
        self.ctrl.set_current(index)

    def set_stage(self, stage: int, jump_unconfirmed: bool = False) -> None:
        if not self.ctrl.has_project() or not (0 <= stage < len(self.page_list)):
            self.step_bar.set_step(self.pages.currentIndex())
            return
        self._commit_page()
        self.ctrl.set_stage(stage)
        self.pages.setCurrentIndex(stage)
        self.step_bar.set_step(stage)
        if jump_unconfirmed and stage == 1:
            j = project_ops.first_unconfirmed(self.ctrl.photos)
            self.ctrl.set_current(j if j is not None else 0)
        page = self.current_page()
        if hasattr(page, "on_enter"):
            page.on_enter()
        self._update_nav()

    def _update_nav(self) -> None:
        if not self.ctrl.has_project():
            return
        n = len(self.ctrl.photos)
        i = self.ctrl.current_index
        self.counter.setText(f"Фото {i + 1} из {n}")
        self.prev_btn.setEnabled(i > 0)
        page = self.current_page()
        self.next_btn.setText(page.next_label() if hasattr(page, "next_label") else "Далее →")
        self.next_btn.setVisible(page.next_label() != "" if hasattr(page, "next_label") else True)
        if hasattr(page, "next_enabled"):
            self.next_btn.setEnabled(page.next_enabled())
        else:
            self.next_btn.setEnabled(True)

    def _on_project_loaded(self) -> None:
        if not self.ctrl.has_project():
            self.stack.setCurrentWidget(self.start_page)
            self.start_page.set_recent(None)
            self.setWindowTitle(APP_TITLE)
            return
        folder = self.ctrl.project.source_dir
        name = Path(folder).name or folder
        self.folder_btn.setText(f"📁 {name}")
        self.folder_btn.setToolTip(folder)
        self.setWindowTitle(f"{name} — {APP_TITLE}")
        self.stack.setCurrentWidget(self.workspace)
        self.set_stage(min(self.ctrl.project.stage, len(self.page_list) - 1))
        cur = self.ctrl.current
        if self.ctrl.project.stage == 0 and cur is not None and not cur.sample_name:
            self.photo_page.name_combo.setFocus()   # можно сразу печатать название

    # ------------------------------------------------------------ папки
    def _startup(self) -> None:
        if self.app_settings.cache_auto():
            # в фоне, чтобы не задерживать запуск; затрагивает только папку кэша
            days = self.app_settings.cache_max_days()
            max_bytes = int(self.app_settings.cache_max_gb() * 1024 ** 3)
            threading.Thread(target=_safe_prune, args=(days, max_bytes), daemon=True).start()
        folder = state.last_session_folder()
        if not folder:
            return
        saved = state.load_project_for(folder)
        if saved is None or not state.project_has_work(saved) or not Path(folder).is_dir():
            self.start_page.set_recent(folder if Path(folder).is_dir() else None)
            return
        done = sum(1 for p in saved.photos if p.params_complete())
        answer = ask_continue(self, folder, done, len(saved.photos))
        if answer is True:
            self._open(folder, saved)
        elif answer is False:
            state.start_new(folder)
            self.start_page.set_recent(None)
        else:
            self.start_page.set_recent(folder)

    def _open_recent(self) -> None:
        folder = state.last_session_folder()
        if folder and Path(folder).is_dir():
            self.open_folder(folder)

    def choose_folder(self) -> None:
        start = self.app_settings.last_folder() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Папка с фотографиями", start)
        if folder:
            self.open_folder(folder)

    def open_folder(self, folder: str) -> None:
        folder = os.path.normpath(folder)
        if self.ctrl.has_project():
            self._commit_page()
            self.ctrl.save_now()
        saved = state.load_project_for(folder)
        if saved is not None and state.project_has_work(saved):
            done = sum(1 for p in saved.photos if p.params_complete())
            answer = ask_continue(self, folder, done, len(saved.photos))
            if answer is None:
                return
            if answer is False:
                state.start_new(folder)
                self._open(folder, None, prefill=False)
                return
        # завершенная работа открывается с разметкой (можно пересобрать)
        self._open(folder, saved)

    def _open(self, folder: str, saved, prefill: bool = True) -> None:
        self.statusBar().showMessage("Поиск фотографий…")
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            self.ctrl.open_folder(folder, saved, prefill=prefill)
        except Exception as e:
            log.exception("Не удалось открыть папку")
            QMessageBox.warning(self, "Папка", f"Не удалось открыть папку:\n{e}")
            return
        finally:
            self.unsetCursor()
            self.statusBar().clearMessage()
        if not self.ctrl.has_project():
            QMessageBox.information(self, "Фотографии не найдены",
                                    "В выбранной папке нет фотографий поддерживаемых форматов.")
            self.stack.setCurrentWidget(self.start_page)
            return
        n = len(self.ctrl.photos)
        no_exif = sum(1 for p in self.ctrl.photos if not p.capture_from_exif)
        msg = f"Найдено фотографий: {n}"
        if no_exif:
            msg += f"  ·  без даты съемки в EXIF: {no_exif} (упорядочены по дате файла)"
        self.statusBar().showMessage(msg, 8000)

    def start_over(self) -> None:
        if not self.ctrl.has_project() or self.final_page.is_busy():
            return
        self._commit_page()
        box = QMessageBox(self)
        box.setWindowTitle("Начать заново")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("Что сделать с текущей работой?")
        box.setInformativeText(
            "«Закрыть и сохранить» — разметку можно будет продолжить позже.\n\n"
            "«Начать новый проект» — удалить сохраненную разметку этой папки и начать "
            "с чистого листа. Фотографии на диске не удаляются, настройки программы сохраняются.")
        keep = box.addButton("Закрыть и сохранить", QMessageBox.ButtonRole.AcceptRole)
        new = box.addButton("Начать новый проект", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(keep)
        box.exec()
        clicked = box.clickedButton()
        folder = self.ctrl.project.source_dir
        if clicked is keep:
            self.ctrl.close_project()
            self.start_page.set_recent(folder)
        elif clicked is new:
            self._start_new_project()

    def _start_new_project(self) -> None:
        folder = self.ctrl.project.source_dir
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            self.ctrl.start_new_project()
        except Exception as e:
            log.exception("Не удалось начать новый проект")
            QMessageBox.warning(self, "Начать заново", f"Не удалось открыть папку заново:\n{e}")
            return
        finally:
            self.unsetCursor()
        if not self.ctrl.has_project():
            self.stack.setCurrentWidget(self.start_page)
            self.start_page.set_recent(None)
            return
        self.set_stage(0)
        self.ctrl.set_current(0)
        self.statusBar().showMessage(
            f"Новый проект: {Path(folder).name} — фотографий: {len(self.ctrl.photos)}. "
            "Прежняя разметка удалена, фотографии не тронуты.", 8000)

    def _open_source_folder(self) -> None:
        open_in_explorer(self.ctrl.project.source_dir)

    def open_settings(self, tab: int = 0) -> None:
        """Настройки шкалы, резкости и экспорта."""
        if not self.ctrl.has_project() or self.final_page.is_busy():
            return
        self._commit_page()
        dlg = SettingsDialog(self.ctrl, self.media, tab if isinstance(tab, int) else 0, self)
        dlg.exec()

    def remove_photos(self, rows: list[int]) -> None:
        """Убрать фото из партии. Файлы на диске остаются; вернуть — Ctrl+Z."""
        if not self._in_workspace() or self.final_page.is_busy() or not rows:
            return
        self._commit_page()
        if len(rows) >= len(self.ctrl.photos):
            QMessageBox.information(self, "Убрать из проекта",
                                    "Нельзя убрать все фотографии партии.\n"
                                    "Чтобы закончить работу с папкой, выберите «Начать заново».")
            return
        n = self.ctrl.remove_photos(rows)
        if n:
            what = "1 фото" if n == 1 else f"{n} фото"
            self.statusBar().showMessage(
                f"Убрано из проекта: {what}. Файлы на диске не тронуты. Вернуть — Ctrl+Z", 6000)

    def _goto_photo_stage(self, index: int, stage: int) -> None:
        self.set_stage(stage)
        self.ctrl.set_current(index)

    def _set_busy(self, busy: bool) -> None:
        """Во время экспорта разметку менять нельзя (просматривать — можно)."""
        for w in (self.step_bar, self.settings_btn, self.folder_btn, self.undo_btn, self.redo_btn,
                  self.remove_btn):
            w.setEnabled(not busy)
        if not busy:
            self.undo_btn.setEnabled(self.ctrl.undo_stack.canUndo())
            self.redo_btn.setEnabled(self.ctrl.undo_stack.canRedo())

    def _can_close(self) -> bool:
        if not self.final_page.is_busy():
            return True
        r = QMessageBox.question(self, "Идет обработка",
                                 "Идет сохранение фотографий. Остановить обработку и закрыть программу?",
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        return r == QMessageBox.StandardButton.Yes

    # ------------------------------------------------------------ закрытие
    def closeEvent(self, e: QCloseEvent) -> None:  # noqa: N802
        if not self._can_close():
            e.ignore()
            return
        self._commit_page()
        self.final_page.shutdown()
        self.ctrl.save_now()
        self.app_settings.set_geometry(self.saveGeometry())
        self.app_settings.sync()
        self.media.shutdown()
        super().closeEvent(e)


def _safe_prune(days: int, max_bytes: int) -> None:
    try:
        cache.prune(days, max_bytes)
    except Exception:
        log.exception("Автоочистка кэша не выполнена")


def open_in_explorer(path: str) -> None:
    if not path:
        return
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
