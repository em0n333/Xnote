#!/usr/bin/env python3
"""
Simple tabbed note editor (plain text + markdown mode)
Requires: PySide6   ->  Arch: sudo pacman -S pyside6   |   anywhere: pip install PySide6
Run:      python notepad.py [file ...]
"""
import os
import re
import sys

from PySide6.QtCore import QDir, QEvent, QRect, QSettings, QSize, QStandardPaths, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction, QColor, QFont, QFontDatabase, QFontMetrics, QKeySequence, QPainter, QShortcut,
    QSyntaxHighlighter, QTextBlockFormat, QTextCharFormat, QTextCursor,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QCompleter, QGridLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTabWidget, QTextEdit, QTreeView, QVBoxLayout, QWidget,
)

# ----------------------------------------------------------------- palette
BG = "#131315"
BG_DARK = "#0e0e10"
FG = "#e6e6e8"
GUTTER = "#47474d"
GUTTER_ACTIVE = "#e6e6e8"
CURRENT_LINE = "#1b1b20"
RED = "#e0535a"
DIM = "#5b5b62"
SELECTION = "#3a2a2e"
GREEN = "#7bb36f"
MATCH = "#5a4a16"  # background of the other search matches
MATCH_LIMIT = 2000  # max matches highlighted at once (keeps huge files snappy)
LINE_HEIGHT = 150  # percent, gives the airy spacing of the original
NATIVE_DIALOGS = False  # True = use your desktop's own open/save dialog instead of the themed one
UI_FONT_SIZE = 12  # size (pt) of the interface text: tabs, status bar, dialogs
GUTTER_FONT_DELTA = 4  # line numbers are this many pt smaller than the editor font
CURSOR_COLOR = RED  # text cursor color
CURSOR_WIDTH = 2  # text cursor width in px

_IPV4 = r"(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_V6 = (r"(?<![\w:])(?:(?:[0-9a-f]{1,4}:){7}[0-9a-f]{1,4}"
       r"|(?:[0-9a-f]{1,4}:){0,6}[0-9a-f]{0,4}::(?:[0-9a-f]{1,4}:){0,6}[0-9a-f]{0,4})")

# Built-in modules (name -> regex). Matching is case-insensitive.
# Add your own in ~/.config/xnote/modules.txt (Ctrl+Shift+P), one per line:   name = regex
DEFAULT_MODULES = {
    "emails": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "asns": r"\bAS\d{1,10}\b",
    "ipv4": rf"\b{_IPV4}\b",
    "cidr-v4": rf"\b{_IPV4}/(?:3[0-2]|[12]?\d)\b",
    "ipv6": rf"{_V6}(?![\w:])",
    "cidr-v6": rf"{_V6}/\d{{1,3}}(?!\d)",
    "urls": r"https?://[^\s\"'<>)\]]+",
    "domains": r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}\b",
    "md5": r"\b[a-f0-9]{32}\b",
    "sha1": r"\b[a-f0-9]{40}\b",
    "sha256": r"\b[a-f0-9]{64}\b",
    "jwt": r"\beyJ[\w-]+\.[\w-]+\.[\w-]*",
    "aws-keys": r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
}
MODULES_TEMPLATE = """# xnote modules: one per line,   name = regex
# Same name as a built-in module overrides it. Lines starting with # are ignored.
# example:
# phone = \\+?\\d[\\d\\s-]{8,}\\d
"""


def modules_path():
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.GenericConfigLocation) or os.path.expanduser("~/.config")
    return os.path.join(base, "xnote", "modules.txt")


def load_modules():
    mods = dict(DEFAULT_MODULES)
    try:
        with open(modules_path(), "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, rx = line.split("=", 1)
                name, rx = name.strip(), rx.strip()
                if name and rx:
                    mods[name] = rx
    except OSError:
        pass
    return mods


DEFAULT_FONTS = ["JetBrains Mono", "JetBrainsMono Nerd Font", "Fira Code",
                 "Cascadia Code", "DejaVu Sans Mono", "Consolas", "Monospace"]
MD_EXT = (".md", ".markdown", ".mdown")

STYLE = f"""
* {{ outline: none; }}
QMainWindow, QWidget#root {{ background: {BG}; }}
QTabWidget::pane {{ border: none; background: {BG}; }}
QTabBar {{ background: {BG_DARK}; }}
QTabBar::tab {{
    background: {BG_DARK}; color: {DIM}; padding: 8px 18px;
    border: none; border-top: 2px solid transparent; min-width: 70px;
}}
QTabBar::tab:selected {{ background: {BG}; color: {FG}; border-top: 2px solid {RED}; }}
QTabBar::tab:hover:!selected {{ color: {FG}; }}
QTabBar::close-button {{ subcontrol-position: right; }}
QMenuBar {{ background: {BG_DARK}; color: {FG}; }}
QMenuBar::item {{ padding: 5px 10px; background: transparent; }}
QMenuBar::item:selected {{ background: {CURRENT_LINE}; }}
QMenu {{ background: {BG_DARK}; color: {FG}; border: 1px solid #222226; padding: 4px; }}
QMenu::item {{ padding: 5px 24px; }}
QMenu::item:selected {{ background: {CURRENT_LINE}; color: {RED}; }}
QStatusBar {{ background: {BG_DARK}; color: {DIM}; }}
QStatusBar::item {{ border: none; }}
QLabel {{ color: {DIM}; }}
QPushButton {{
    background: transparent; color: {DIM}; border: 1px solid #2a2a2f;
    padding: 2px 10px; border-radius: 3px;
}}
QPushButton:checked {{ color: {RED}; border-color: {RED}; }}
QLineEdit {{
    background: {BG}; color: {FG}; border: 1px solid #2a2a2f;
    padding: 1px 6px; border-radius: 3px; min-width: 170px;
}}
QSpinBox {{
    background: {BG}; color: {FG}; border: 1px solid #2a2a2f;
    padding: 1px 6px; border-radius: 3px; min-width: 62px;
}}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; }}
QScrollBar:vertical {{ background: {BG}; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #26262b; min-height: 30px; border-radius: 5px; }}
QScrollBar::handle:vertical:hover {{ background: #34343a; }}
QScrollBar:horizontal {{ background: {BG}; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: #26262b; min-width: 30px; border-radius: 5px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
"""


# ------------------------------------------------------- markdown highlight
def _fmt(color, bold=False, italic=False):
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Weight.Bold)
    f.setFontItalic(italic)
    return f


class MarkdownHighlighter(QSyntaxHighlighter):
    HEADING = re.compile(r"^(#{1,6})(\s+)(.*)$")
    LIST = re.compile(r"^(\s*)([-*+]|\d+[.)])(\s+)")
    CHECK = re.compile(r"\[( |x|X)\]")
    COMMENT = re.compile(r"<!--.*?(-->|$)")
    BOLD = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
    ITALIC = re.compile(r"(?<![*\w])([*_])(?=\S)(.+?)(?<=\S)\1(?![*\w])")
    CODE = re.compile(r"`[^`]+`")
    LINK = re.compile(r"\[[^\]]*\]\([^)]*\)")
    QUOTE = re.compile(r"^\s*>.*$")
    RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")

    def __init__(self, doc):
        super().__init__(doc)
        self.f_hash = _fmt(RED)
        self.f_head = _fmt("#ffffff")
        self.f_marker = _fmt(DIM)
        self.f_box = _fmt(RED)
        self.f_done = _fmt(GREEN)
        self.f_comment = _fmt(DIM)
        self.f_bold = _fmt("#ffffff", bold=True)
        self.f_italic = _fmt(FG, italic=True)
        self.f_code = _fmt("#d4a373")
        self.f_link = _fmt("#6fa8dc")
        self.f_quote = _fmt("#8a8a92", italic=True)

    def highlightBlock(self, text):
        in_fence = self.previousBlockState() == 1
        if text.lstrip().startswith("```"):
            self.setCurrentBlockState(0 if in_fence else 1)
            self.setFormat(0, len(text), self.f_code)
            return
        if in_fence:
            self.setCurrentBlockState(1)
            self.setFormat(0, len(text), self.f_code)
            return
        self.setCurrentBlockState(0)
        if not text.strip():
            return

        m = self.HEADING.match(text)
        if m:
            self.setFormat(m.start(1), len(m.group(1)), self.f_hash)
            self.setFormat(m.start(3), len(m.group(3)), self.f_head)
        elif self.QUOTE.match(text):
            self.setFormat(0, len(text), self.f_quote)
        elif self.RULE.match(text):
            self.setFormat(0, len(text), self.f_marker)

        m = self.LIST.match(text)
        if m:
            self.setFormat(m.start(2), len(m.group(2)), self.f_marker)

        if "[" in text:
            for m in self.CHECK.finditer(text):
                f = self.f_box if m.group(1) == " " else self.f_done
                self.setFormat(m.start(), m.end() - m.start(), f)

        if "*" in text or "_" in text or "`" in text or "](" in text:
            for rx, f in ((self.BOLD, self.f_bold), (self.ITALIC, self.f_italic),
                          (self.LINK, self.f_link), (self.CODE, self.f_code)):
                for m in rx.finditer(text):
                    self.setFormat(m.start(), m.end() - m.start(), f)

        if "<!--" in text:
            for m in self.COMMENT.finditer(text):  # last so it wins
                self.setFormat(m.start(), m.end() - m.start(), self.f_comment)


# ------------------------------------------------------------------ editor
class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_gutter(event)


class Editor(QPlainTextEdit):
    zoomRequested = Signal(int)  # +1 / -1

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoomRequested.emit(1 if e.angleDelta().y() > 0 else -1)
            e.accept()
            return
        super().wheelEvent(e)

    def __init__(self, path=None, markdown=False):
        super().__init__()
        self.path = path
        self.match_sels = []  # search highlights, see FindBar
        self.module_copy = None  # set by FindBar: Ctrl+C with no selection copies all matches
        self.show_numbers = True
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.document().setDocumentMargin(4)
        self.gutter = LineNumberArea(self)
        self.gutter.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        pal = self.palette()
        pal.setColor(pal.ColorRole.Base, QColor(BG))
        pal.setColor(pal.ColorRole.Text, QColor(FG))
        pal.setColor(pal.ColorRole.Highlight, QColor(SELECTION))
        pal.setColor(pal.ColorRole.HighlightedText, QColor(FG))
        self.setPalette(pal)
        self.highlighter = MarkdownHighlighter(None)
        self.markdown = False
        self.set_markdown(markdown)

        self.blockCountChanged.connect(self.update_margins)
        self.updateRequest.connect(self.update_gutter)
        self._last_block = -1
        self.cursorPositionChanged.connect(self.on_cursor)
        self.update_margins()
        self.highlight_line()

        # Qt always draws its own cursor in the text color, so hide it and paint ours
        self.setCursorWidth(0)
        self._blink_on = True
        self._blink = QTimer(self)
        self._blink.timeout.connect(self._toggle_blink)
        flash = QApplication.cursorFlashTime()
        if flash > 0:
            self._blink.start(flash // 2)
        self.cursorPositionChanged.connect(self._reset_blink)

    def _toggle_blink(self):
        self._blink_on = not self._blink_on
        self.viewport().update()

    def _reset_blink(self):
        self._blink_on = True
        if self._blink.isActive():
            self._blink.start()
        self.viewport().update()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._blink_on and self.hasFocus() and not self.isReadOnly():
            r = self.cursorRect()
            p = QPainter(self.viewport())
            p.fillRect(r.left(), r.top(), CURSOR_WIDTH, r.height(), QColor(CURSOR_COLOR))
            p.end()

    def keyPressEvent(self, e):
        if (e.matches(QKeySequence.StandardKey.Copy) and not self.textCursor().hasSelection()
                and self.module_copy and self.module_copy()):
            return
        super().keyPressEvent(e)

    def on_cursor(self):
        b = self.textCursor().blockNumber()
        if b != self._last_block:
            self._last_block = b
            self.highlight_line()
            self.gutter.update()

    # --- content helpers
    def set_content(self, text):
        doc = self.document()
        doc.setUndoRedoEnabled(False)
        self.setPlainText(text)
        if LINE_HEIGHT != 100:
            cur = QTextCursor(doc)
            cur.select(QTextCursor.SelectionType.Document)
            bf = QTextBlockFormat()
            bf.setLineHeight(LINE_HEIGHT, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
            cur.mergeBlockFormat(bf)
            cur.clearSelection()
        doc.setUndoRedoEnabled(True)
        doc.setModified(False)
        self.moveCursor(QTextCursor.MoveOperation.Start)

    def set_markdown(self, on):
        self.markdown = on
        self.highlighter.setDocument(self.document() if on else None)

    def set_editor_font(self, font):
        self.setFont(font)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.update_margins()
        self.gutter.update()

    # --- gutter
    def gutter_font(self):
        f = QFont(self.font())
        f.setPointSizeF(max(1.0, self.font().pointSizeF() - GUTTER_FONT_DELTA))
        return f

    def set_wrap(self, on):
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth if on
                             else QPlainTextEdit.LineWrapMode.NoWrap)
        self.gutter.update()

    def set_line_numbers(self, on):
        self.show_numbers = on
        self.gutter.setVisible(on)
        self.update_margins()
        self.gutter.update()

    def gutter_width(self):
        if not self.show_numbers:
            return 5  # left padding when line numbers are off
        digits = max(2, len(str(self.blockCount())))
        return 26 + QFontMetrics(self.gutter_font()).horizontalAdvance("9") * digits + 22

    def update_margins(self, *_):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def update_gutter(self, rect, dy):
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_margins()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        cr = self.contentsRect()
        self.gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def paint_gutter(self, event):
        p = QPainter(self.gutter)
        p.fillRect(event.rect(), QColor(BG))
        block = self.firstVisibleBlock()
        num = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        cur = self.textCursor().blockNumber()
        fr = self.gutter_font()
        fb = QFont(fr)
        fb.setBold(True)
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                p.setFont(fb if num == cur else fr)
                p.setPen(QColor(GUTTER_ACTIVE if num == cur else GUTTER))
                h = bottom - top
                lay = block.layout()
                if self.lineWrapMode() != QPlainTextEdit.LineWrapMode.NoWrap and lay and lay.lineCount():
                    h = min(h, round(lay.lineAt(0).height()))  # first visual line only
                p.drawText(0, top, self.gutter.width() - 22, h,
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                           str(num + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            num += 1

    def highlight_line(self):
        sel = QTextEdit.ExtraSelection()
        sel.format.setBackground(QColor(CURRENT_LINE))
        sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        sel.cursor = self.textCursor()
        sel.cursor.clearSelection()
        self.setExtraSelections([sel] + self.match_sels)

    def set_matches(self, sels):
        self.match_sels = sels
        self.highlight_line()


# ---------------------------------------------------------------- find bar
class FindBar(QWidget):
    """Sublime-style find / replace bar.  Ctrl+F = find, Ctrl+H = find + replace."""

    def __init__(self, get_editor, parent=None):
        super().__init__(parent)
        self.setObjectName("findbar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setStyleSheet(f"QWidget#findbar {{ background: {BG_DARK}; }}")
        self._get_editor = get_editor
        self._ed = None
        self._note = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(lambda: self._update(False))

        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Find")
        self.find_edit.textChanged.connect(self._changed)
        self.find_edit.returnPressed.connect(self._enter_find)
        self.repl_edit = QLineEdit()
        self.repl_edit.setPlaceholderText("Replace")
        self.repl_edit.returnPressed.connect(self.replace_one)
        self.regex_btn = self._toggle(".*", "Regular expression (Alt+R)", "Alt+R")
        self.case_btn = self._toggle("Aa", "Match case (Alt+C)", "Alt+C")
        self.word_btn = self._toggle("Word", "Whole word (Alt+W)", "Alt+W")
        prev_btn = self._button("Prev", lambda: self.find(False))
        next_btn = self._button("Next", lambda: self.find(True))
        self.count_label = QLabel("")
        self.count_label.setMinimumWidth(90)
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        close_btn = self._button("\u00d7", self.close_bar)
        rep_btn = self._button("Replace", self.replace_one)
        repall_btn = self._button("Replace All", self.replace_all)
        self._rep_widgets = [self.repl_edit, rep_btn, repall_btn]

        g = QGridLayout(self)
        g.setContentsMargins(8, 6, 8, 6)
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(6)
        g.setColumnStretch(0, 1)
        g.addWidget(self.find_edit, 0, 0)
        g.addWidget(self.regex_btn, 0, 1)
        g.addWidget(self.case_btn, 0, 2)
        g.addWidget(self.word_btn, 0, 3)
        g.addWidget(prev_btn, 0, 4)
        g.addWidget(next_btn, 0, 5)
        g.addWidget(self.count_label, 0, 6)
        g.addWidget(close_btn, 0, 7)
        g.addWidget(self.repl_edit, 1, 0)
        g.addWidget(rep_btn, 1, 1, 1, 3)
        g.addWidget(repall_btn, 1, 4, 1, 2)
        self.hide()

    # --- small builders
    def _button(self, text, slot):
        b = QPushButton(text)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # keep keyboard focus in the text fields
        b.clicked.connect(slot)
        return b

    def _toggle(self, text, tip, key):
        b = QPushButton(text)
        b.setCheckable(True)
        b.setToolTip(tip)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.toggled.connect(self._changed)
        sc = QShortcut(QKeySequence(key), self)
        sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc.activated.connect(b.toggle)
        return b

    # --- show / hide
    def open(self, replace=False):
        ed = self._get_editor()
        if ed is None:
            return
        self.attach(ed)
        if self.isHidden():
            for w in self._rep_widgets:
                w.setVisible(False)
        if replace:
            for w in self._rep_widgets:
                w.setVisible(True)
        self.setVisible(True)
        c = ed.textCursor()
        if c.hasSelection():
            t = c.selectedText()
            if "\u2029" not in t and len(t) < 200:  # single-line selection -> search for it
                self.find_edit.setText(t)
        self._update(False)
        target = self.repl_edit if (replace and self.find_edit.text()) else self.find_edit
        target.setFocus()
        target.selectAll()

    def show_pattern(self, pattern):
        """Highlight every match of a regex (used by the modules picker)."""
        ed = self._get_editor()
        if ed is None:
            return
        self.attach(ed)
        if self.isHidden():
            for w in self._rep_widgets:
                w.setVisible(False)
        self.setVisible(True)
        for b, on in ((self.regex_btn, True), (self.case_btn, False), (self.word_btn, False)):
            b.blockSignals(True)
            b.setChecked(on)
            b.blockSignals(False)
        self.find_edit.blockSignals(True)
        self.find_edit.setText(pattern)
        self.find_edit.blockSignals(False)
        c = ed.textCursor()
        c.clearSelection()
        ed.setTextCursor(c)
        self._note = ""
        self._update(False)
        n = len(self.matches_text().splitlines())
        self.count_label.setText(f"{n} unique" if n else "No results")
        ed.module_copy = self.copy_matches
        ed.setFocus()

    def matches_text(self):
        """All matches, one per line, duplicates removed, first-seen order."""
        ed = self._get_editor()
        pat = self._pattern()
        if self.isHidden() or ed is None or pat is None:
            return ""
        return "\n".join(dict.fromkeys(m.group(0) for _s, _e, m in self._matches(ed, pat)))

    def copy_matches(self):
        text = self.matches_text()
        if not text:
            return False
        QApplication.clipboard().setText(text)
        self._note = f"Copied {len(text.splitlines())}"
        self.count_label.setText(self._note)
        return True

    def close_bar(self, *_):
        self.hide()
        self._clear()
        ed = self._get_editor()
        if ed:
            ed.setFocus()

    def close_if_open(self):
        if not self.isHidden():
            self.close_bar()

    # --- follow the active tab
    def attach(self, ed):
        if ed is self._ed:
            return
        if self._ed is not None:
            try:
                self._ed.document().contentsChanged.disconnect(self._schedule)
            except (RuntimeError, TypeError):
                pass
        self._clear()
        self._ed = ed
        if ed is not None:
            ed.document().contentsChanged.connect(self._schedule)

    def on_tab_changed(self, *_):
        self.attach(self._get_editor())
        if not self.isHidden():
            self._update(False)

    def _clear(self):
        if self._ed is not None:
            try:
                self._ed.set_matches([])
            except RuntimeError:  # editor already deleted
                pass

    def _schedule(self):
        if not self.isHidden():
            self._timer.start()

    # --- searching
    def _pattern(self):
        text = self.find_edit.text()
        if not text:
            return None
        body = text if self.regex_btn.isChecked() else re.escape(text)
        if self.word_btn.isChecked():
            body = rf"(?<!\w)(?:{body})(?!\w)"
        flags = re.MULTILINE | (0 if self.case_btn.isChecked() else re.IGNORECASE)
        try:
            return re.compile(body, flags)
        except (re.error, RecursionError, OverflowError):
            return None

    def _matches(self, ed, pat, include_empty=False):
        """[(start, end, match), ...] in the editor's own (UTF-16) positions."""
        text = ed.toPlainText()
        offs = None
        if text and max(text) > "\uffff":  # emoji etc. count as 2 in Qt, 1 in Python
            offs = [0]
            for ch in text:
                offs.append(offs[-1] + (2 if ch > "\uffff" else 1))
        out = []
        for m in pat.finditer(text):
            s, e = m.span()
            if s == e and not include_empty:
                continue
            if offs:
                s, e = offs[s], offs[e]
            out.append((s, e, m))
        return out

    def _select(self, ed, match):
        c = ed.textCursor()
        c.setPosition(match[0])
        c.setPosition(match[1], QTextCursor.MoveMode.KeepAnchor)
        ed.setTextCursor(c)
        if not ed.viewport().rect().adjusted(0, 40, 0, -40).contains(ed.cursorRect()):
            ed.centerCursor()

    def _paint(self, ed, matches):
        sels = []
        doc = ed.document()
        for s, e, _m in matches[:MATCH_LIMIT]:
            sel = QTextEdit.ExtraSelection()
            sel.format.setBackground(QColor(MATCH))
            c = QTextCursor(doc)
            c.setPosition(s)
            c.setPosition(e, QTextCursor.MoveMode.KeepAnchor)
            sel.cursor = c
            sels.append(sel)
        ed.set_matches(sels)

    def _update(self, move=False):
        ed = self._get_editor()
        if ed is None:
            return
        if ed is not self._ed:
            self.attach(ed)
        text = self.find_edit.text()
        pat = self._pattern()
        bad = bool(text) and pat is None
        self.find_edit.setStyleSheet(f"border: 1px solid {RED};" if bad else "")
        matches = self._matches(ed, pat) if pat else []
        self._paint(ed, matches)
        if move and matches:
            start = ed.textCursor().selectionStart()
            self._select(ed, next((x for x in matches if x[0] >= start), matches[0]))
        c = ed.textCursor()
        sel = (c.selectionStart(), c.selectionEnd())
        idx = next((i for i, x in enumerate(matches, 1) if (x[0], x[1]) == sel), 0)
        if self._note:
            msg = self._note
        elif not text:
            msg = ""
        elif pat is None:
            msg = "Invalid regex"
        elif not matches:
            msg = "No results"
        elif idx:
            msg = f"{idx} of {len(matches)}"
        else:
            msg = f"{len(matches)} match" + ("" if len(matches) == 1 else "es")
        self.count_label.setText(msg)
        self.count_label.setStyleSheet(
            f"color: {RED};" if msg in ("No results", "Invalid regex") else "")

    def _changed(self, *_):
        self._note = ""
        self._update(True)

    def _enter_find(self):
        shift = QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier
        self.find(not shift)

    def find(self, forward=True):
        if self.isHidden():
            self.open(False)
            return
        self._note = ""
        ed = self._get_editor()
        pat = self._pattern()
        if ed is None or pat is None:
            self._update(False)
            return
        matches = self._matches(ed, pat)
        if matches:
            c = ed.textCursor()
            if forward:
                pos = c.selectionEnd()
                pick = next((x for x in matches if x[0] >= pos), matches[0])
            else:
                pos = c.selectionStart()
                pick = next((x for x in reversed(matches) if x[1] <= pos), matches[-1])
            self._select(ed, pick)
        self._update(False)

    # --- replacing
    def _expand(self, m):
        r = self.repl_edit.text()
        if not self.regex_btn.isChecked():
            return r
        try:
            return m.expand(re.sub(r"\$(\d+)", r"\\g<\1>", r))  # $1 and \1 both work
        except (re.error, IndexError):
            self.count_label.setText("Bad replacement")
            return None

    def replace_one(self, *_):
        ed = self._get_editor()
        pat = self._pattern()
        if ed is None or pat is None:
            return
        self._note = ""
        c = ed.textCursor()
        sel = (c.selectionStart(), c.selectionEnd())
        cur = next((x for x in self._matches(ed, pat) if (x[0], x[1]) == sel), None)
        if cur is None:  # nothing selected that matches yet: just jump to the next one
            self.find(True)
            return
        r = self._expand(cur[2])
        if r is None:
            return
        c.insertText(r)
        ed.setTextCursor(c)
        self.find(True)

    def replace_all(self, *_):
        ed = self._get_editor()
        pat = self._pattern()
        if ed is None or pat is None:
            return
        matches = self._matches(ed, pat, include_empty=True)
        if not matches:
            return
        reps = []
        for _s, _e, m in matches:
            r = self._expand(m)
            if r is None:
                return
            reps.append(r)
        c = QTextCursor(ed.document())
        c.beginEditBlock()  # one undo step for the whole thing
        for (s, e, _m), r in zip(reversed(matches), reversed(reps)):  # back to front
            c.setPosition(s)
            c.setPosition(e, QTextCursor.MoveMode.KeepAnchor)
            c.insertText(r)
        c.endEditBlock()
        self._note = f"Replaced {len(matches)}"
        self._update(False)


# ------------------------------------------------------------- main window
DIALOG_STYLE = f"""
QFileDialog, QFileDialog QWidget {{ background: {BG}; color: {FG}; }}
QFileDialog QLabel {{ color: {DIM}; }}
QFileDialog QTreeView, QFileDialog QListView {{
    background: {BG}; alternate-background-color: {BG}; color: {FG};
    border: 1px solid #222226; outline: 0;
    selection-background-color: {CURRENT_LINE}; selection-color: {RED};
}}
QFileDialog QTreeView::item, QFileDialog QListView::item {{ padding: 4px 2px; }}
QFileDialog QTreeView::item:hover, QFileDialog QListView::item:hover {{ background: #17171a; }}
QFileDialog QHeaderView::section {{
    background: {BG_DARK}; color: {DIM}; border: none; padding: 6px 8px;
}}
QFileDialog QLineEdit {{
    background: {BG_DARK}; color: {FG}; border: 1px solid #2a2a2f;
    padding: 6px 8px; border-radius: 3px; selection-background-color: {SELECTION};
}}
QFileDialog QLineEdit:focus {{ border-color: {RED}; }}
QFileDialog QComboBox {{
    background: {BG_DARK}; color: {FG}; border: 1px solid #2a2a2f;
    padding: 5px 8px; border-radius: 3px;
}}
QFileDialog QComboBox::drop-down {{ border: none; width: 22px; }}
QFileDialog QComboBox QAbstractItemView {{
    background: {BG_DARK}; color: {FG}; border: 1px solid #222226;
    selection-background-color: {CURRENT_LINE}; selection-color: {RED}; outline: 0;
}}
QFileDialog QToolButton {{ background: transparent; border: none; padding: 5px; border-radius: 3px; }}
QFileDialog QToolButton:hover {{ background: {CURRENT_LINE}; }}
QFileDialog QToolButton:checked {{ background: {CURRENT_LINE}; }}
QFileDialog QPushButton {{
    background: {CURRENT_LINE}; color: {FG}; border: 1px solid #2a2a2f;
    padding: 6px 22px; border-radius: 3px; min-width: 60px;
}}
QFileDialog QPushButton:hover {{ border-color: {RED}; }}
QFileDialog QPushButton:default {{ border-color: {RED}; color: {RED}; }}
QFileDialog QPushButton:disabled {{ color: {DIM}; border-color: #1f1f23; }}
QFileDialog QSplitter::handle {{ background: #222226; width: 1px; }}
"""

MESSAGE_STYLE = f"""
QMessageBox, QMessageBox QWidget {{ background: {BG}; color: {FG}; }}
QMessageBox QLabel {{ color: {FG}; background: transparent; }}
QMessageBox QPushButton {{
    background: {CURRENT_LINE}; color: {FG}; border: 1px solid #2a2a2f;
    padding: 6px 22px; border-radius: 3px; min-width: 70px;
}}
QMessageBox QPushButton:hover {{ border-color: {RED}; }}
QMessageBox QPushButton:default {{ border-color: {RED}; color: {RED}; }}
QMessageBox QPushButton:focus {{ border-color: {RED}; }}
"""


PICKER_STYLE = f"""
QDialog {{ background: {BG_DARK}; border: 1px solid {RED}; }}
QLineEdit {{ background: {BG_DARK}; color: {FG}; border: none; padding: 6px 8px; }}
QListWidget {{ background: {BG_DARK}; color: {FG}; border: none; outline: 0; }}
QListWidget::item {{ padding: 0px 8px; }}
QListWidget::item:selected {{ background: #5a2a2e; color: {FG}; }}
"""


class ModulePicker(QDialog):
    """Rofi-style list of regex modules: type to filter, Enter to pick."""

    def __init__(self, modules, parent=None):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.modules = modules
        self.chosen = None
        self.setStyleSheet(PICKER_STYLE)
        self.setFixedSize(560, 330)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Search modules")
        self.list = QListWidget()
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.setSpacing(0)
        self.list.setUniformItemSizes(True)
        lay.addWidget(self.edit)
        lay.addWidget(self.list)
        self.edit.textChanged.connect(self.refill)
        self.edit.returnPressed.connect(self.pick)
        self.list.itemClicked.connect(lambda _i: self.pick())
        self.edit.installEventFilter(self)
        self.refill()

    def refill(self, *_):
        words = self.edit.text().lower().split()
        self.list.clear()
        for name, rx in self.modules.items():
            if all(w in name.lower() for w in words):
                it = QListWidgetItem(name)
                it.setSizeHint(QSize(0, 30))  # fixed row height = selection bar height
                it.setToolTip(rx)
                it.setData(Qt.ItemDataRole.UserRole, rx)
                self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)

    def eventFilter(self, obj, ev):
        if obj is self.edit and ev.type() == QEvent.Type.KeyPress:
            step = {Qt.Key.Key_Down: 1, Qt.Key.Key_Up: -1}.get(ev.key())
            if step and self.list.count():
                self.list.setCurrentRow((self.list.currentRow() + step) % self.list.count())
                return True
        return super().eventFilter(obj, ev)

    def pick(self):
        it = self.list.currentItem()
        if it:
            self.chosen = it.data(Qt.ItemDataRole.UserRole)
            self.accept()

    def showEvent(self, e):
        super().showEvent(e)
        p = self.parent().frameGeometry()
        self.move(p.x() + (p.width() - self.width()) // 2, p.y() + p.height() // 5)
        self.edit.setFocus()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Notes")
        self.resize(1000, 680)
        self.settings = QSettings("SimpleNotes", "Notes")
        self.untitled = 0
        try:
            self.font_size = max(6, min(72, int(self.settings.value("font_size", 12))))
        except (TypeError, ValueError):
            self.font_size = 12
        self.font_ = self.initial_font()
        self.line_numbers = self.settings.value("line_numbers", True, type=bool)
        self.wrap = self.settings.value("wrap", False, type=bool)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.find_bar = FindBar(self.current)
        self.tabs.currentChanged.connect(self.find_bar.on_tab_changed)
        esc = QShortcut(QKeySequence("Escape"), self)
        esc.activated.connect(self.find_bar.close_if_open)
        root = QWidget()
        root.setObjectName("root")
        lay = QVBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.tabs)
        lay.addWidget(self.find_bar)
        self.setCentralWidget(root)

        self.build_menu()
        self.build_statusbar()
        self.apply_ui_font()
        self.new_tab(markdown=True)

    # --- setup
    def initial_font(self):
        saved = self.settings.value("font_family", "")
        families = set(QFontDatabase.families())
        family = saved if saved in families else next(
            (f for f in DEFAULT_FONTS if f in families), None)
        font = QFont(family) if family else QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPointSize(self.font_size)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setKerning(False)
        return font

    def act(self, menu, text, slot, shortcut=None, checkable=False):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        menu.addAction(a)
        self.addAction(a)  # keeps the shortcut working while the menu bar is hidden
        return a

    def build_menu(self):
        m = self.menuBar().addMenu("&File")
        self.act(m, "New", lambda: self.new_tab(markdown=True), "Ctrl+N")
        self.act(m, "Open...", self.open_files, "Ctrl+O")
        m.addSeparator()
        self.act(m, "Save", self.save, "Ctrl+S")
        self.act(m, "Save As...", self.save_as, "Ctrl+Shift+S")
        m.addSeparator()
        self.act(m, "Close Tab", lambda: self.close_tab(self.tabs.currentIndex()), "Ctrl+W")
        self.act(m, "Quit", self.close, "Ctrl+Q")
        v = self.menuBar().addMenu("&View")
        self.md_action = self.act(v, "Markdown Mode", self.toggle_markdown, "Ctrl+M", True)
        self.sb_action = self.act(v, "Status Bar", self.toggle_statusbar, "Ctrl+B", True)
        self.sb_action.setChecked(True)
        v.addSeparator()
        zin = self.act(v, "Zoom In", lambda: self.zoom(1))
        zin.setShortcuts([QKeySequence("Ctrl++"), QKeySequence("Ctrl+=")])
        self.act(v, "Zoom Out", lambda: self.zoom(-1), "Ctrl+-")
        self.act(v, "Reset Zoom", lambda: self.size_box.setValue(12), "Ctrl+0")
        e = self.menuBar().addMenu("&Edit")
        self.act(e, "Find...", lambda: self.find_bar.open(False), "Ctrl+F")
        self.act(e, "Replace...", lambda: self.find_bar.open(True), "Ctrl+H")
        e.addSeparator()
        self.act(e, "Find Next", lambda: self.find_bar.find(True), "F3")
        self.act(e, "Find Previous", lambda: self.find_bar.find(False), "Shift+F3")
        e.addSeparator()
        self.act(e, "Modules...", self.open_modules, "Ctrl+P")
        self.act(e, "Edit Modules File", self.edit_modules, "Ctrl+Shift+P")
        self.menuBar().hide()  # no top bar; everything is on shortcuts

    def build_statusbar(self):
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        self.pos_label = QLabel("Ln 1, Col 1")
        self.md_button = QPushButton("Markdown")
        self.md_button.setCheckable(True)
        self.md_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.md_button.clicked.connect(self.toggle_markdown)
        self.ln_button = QPushButton("Lines")
        self.ln_button.setCheckable(True)
        self.ln_button.setChecked(self.line_numbers)
        self.ln_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ln_button.setToolTip("Toggle line numbers")
        self.ln_button.clicked.connect(self.toggle_line_numbers)
        self.wrap_button = QPushButton("Wrap")
        self.wrap_button.setCheckable(True)
        self.wrap_button.setChecked(self.wrap)
        self.wrap_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.wrap_button.setToolTip("Toggle line wrapping")
        self.wrap_button.clicked.connect(self.toggle_wrap)
        self.font_box = QLineEdit(self.font_.family())
        self.font_box.setPlaceholderText("Font family")
        self.font_box.setFixedWidth(200)
        comp = QCompleter(QFontDatabase.families(), self.font_box)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        comp.setMaxVisibleItems(10)
        comp.popup().setStyleSheet(
            f"QListView {{ background: {BG_DARK}; color: {FG}; border: 1px solid #222226; }}"
            f"QListView::item:selected {{ background: {CURRENT_LINE}; color: {RED}; }}")
        self.font_box.setCompleter(comp)
        self.font_box.returnPressed.connect(self.font_entered)
        comp.activated[str].connect(self.font_entered)
        self.size_box = QSpinBox()
        self.size_box.setRange(6, 72)
        self.size_box.setSuffix(" pt")
        self.size_box.setValue(self.font_size)
        self.size_box.valueChanged.connect(self.set_size)
        sb.addWidget(self.pos_label)
        sb.addPermanentWidget(self.wrap_button)
        sb.addPermanentWidget(self.ln_button)
        sb.addPermanentWidget(self.md_button)
        sb.addPermanentWidget(self.size_box)
        sb.addPermanentWidget(self.font_box)

    # --- tabs
    def current(self):
        return self.tabs.currentWidget()

    def new_tab(self, path=None, text="", markdown=False):
        ed = Editor(path, markdown)
        ed.set_editor_font(self.font_)
        ed.set_line_numbers(self.line_numbers)
        ed.set_wrap(self.wrap)
        ed.set_content(text)
        if path:
            title = os.path.basename(path)
        else:
            self.untitled += 1
            title = "untitled" if self.untitled == 1 else f"untitled {self.untitled}"
        idx = self.tabs.addTab(ed, title)
        self.tabs.setTabToolTip(idx, path or title)
        ed.document().modificationChanged.connect(lambda _m, e=ed: self.refresh_title(e))
        ed.cursorPositionChanged.connect(self.update_pos)
        ed.zoomRequested.connect(self.zoom)
        self.tabs.setCurrentIndex(idx)
        self.update_tabbar()
        ed.setFocus()
        return ed

    def update_tabbar(self):
        # with a single tab the whole tab bar is hidden (name stays in the window title)
        self.tabs.tabBar().setVisible(self.tabs.count() > 1)

    def toggle_line_numbers(self, *_):
        self.line_numbers = not self.line_numbers
        self.settings.setValue("line_numbers", self.line_numbers)
        self.ln_button.setChecked(self.line_numbers)
        for i in range(self.tabs.count()):
            self.tabs.widget(i).set_line_numbers(self.line_numbers)

    def toggle_wrap(self, *_):
        self.wrap = not self.wrap
        self.settings.setValue("wrap", self.wrap)
        self.wrap_button.setChecked(self.wrap)
        for i in range(self.tabs.count()):
            self.tabs.widget(i).set_wrap(self.wrap)

    def toggle_statusbar(self, *_):
        show = not self.statusBar().isVisible()
        self.statusBar().setVisible(show)
        self.sb_action.setChecked(show)

    def refresh_title(self, ed):
        idx = self.tabs.indexOf(ed)
        if idx < 0:
            return
        base = os.path.basename(ed.path) if ed.path else self.tabs.tabText(idx).lstrip("● ")
        self.tabs.setTabText(idx, ("● " if ed.document().isModified() else "") + base)

    def on_tab_changed(self, _):
        ed = self.current()
        if not ed:
            return
        self.md_action.setChecked(ed.markdown)
        self.md_button.setChecked(ed.markdown)
        self.update_pos()
        self.update_tabbar()
        self.setWindowTitle(f"{self.tabs.tabText(self.tabs.currentIndex()).lstrip('● ')} - Notes")

    def update_pos(self):
        ed = self.current()
        if ed:
            c = ed.textCursor()
            self.pos_label.setText(f"Ln {c.blockNumber() + 1}, Col {c.positionInBlock() + 1}")

    def ask(self, title, text, buttons, default=None, escape=None):
        """Themed message box. buttons = [(key, label), ...]; returns the clicked key."""
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(QMessageBox.Icon.NoIcon)
        box.setStyleSheet(MESSAGE_STYLE)
        made = {}
        for key, label in buttons:
            role = (QMessageBox.ButtonRole.RejectRole if key == escape
                    else QMessageBox.ButtonRole.AcceptRole)
            made[key] = box.addButton(label, role)
        if default in made:
            box.setDefaultButton(made[default])
        if escape in made:
            box.setEscapeButton(made[escape])
        box.exec()
        clicked = box.clickedButton()
        return next((k for k, b in made.items() if b is clicked), escape)

    def error(self, title, text):
        self.ask(title, text, [("ok", "OK")], default="ok", escape="ok")

    def close_tab(self, idx):
        ed = self.tabs.widget(idx)
        if not ed:
            return True
        if ed.document().isModified():
            self.tabs.setCurrentIndex(idx)
            name = self.tabs.tabText(idx).lstrip("● ")
            r = self.ask(
                "Unsaved changes", f"Save changes to “{name}”?",
                [("save", "Save"), ("discard", "Discard"), ("cancel", "Cancel")],
                default="save", escape="cancel")
            if r == "cancel":
                return False
            if r == "save" and not self.save():
                return False
        self.tabs.removeTab(idx)
        ed.deleteLater()
        if self.tabs.count() == 0:
            self.new_tab(markdown=True)
        self.update_tabbar()
        return True

    # --- files
    FILTERS = ["All files (*)", "Markdown (*.md *.markdown)", "Text (*.txt)"]

    def themed_dialog(self, title, start_dir):
        dlg = QFileDialog(self, title, start_dir)
        dlg.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dlg.setNameFilters(self.FILTERS)
        dlg.setViewMode(QFileDialog.ViewMode.Detail)
        dlg.setStyleSheet(DIALOG_STYLE)
        dlg.resize(860, 540)
        places = [QDir.homePath()] + [
            QStandardPaths.writableLocation(loc) for loc in (
                QStandardPaths.StandardLocation.DocumentsLocation,
                QStandardPaths.StandardLocation.DesktopLocation,
                QStandardPaths.StandardLocation.DownloadLocation)]
        dlg.setSidebarUrls([QUrl.fromLocalFile(d) for d in places if d and os.path.isdir(d)])
        tree = dlg.findChild(QTreeView, "treeView")
        if tree:
            tree.setColumnHidden(2, True)  # drop the "Type" column
            tree.setRootIsDecorated(False)
        return dlg

    def start_dir(self):
        d = self.settings.value("last_dir", "")
        return d if d and os.path.isdir(d) else QDir.homePath()

    def pick_open(self):
        if NATIVE_DIALOGS:
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Open files", self.start_dir(), ";;".join(self.FILTERS))
        else:
            dlg = self.themed_dialog("Open files", self.start_dir())
            dlg.setFileMode(QFileDialog.FileMode.ExistingFiles)
            dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
            paths = dlg.selectedFiles() if dlg.exec() else []
        if paths:
            self.settings.setValue("last_dir", os.path.dirname(paths[0]))
        return paths

    def pick_save(self, start):
        folder = os.path.dirname(start) if os.path.isabs(start) else self.start_dir()
        name = os.path.basename(start)
        if NATIVE_DIALOGS:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save file", os.path.join(folder, name), ";;".join(self.FILTERS))
        else:
            dlg = self.themed_dialog("Save file", folder)
            dlg.setFileMode(QFileDialog.FileMode.AnyFile)
            dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
            dlg.selectFile(name)
            path = dlg.selectedFiles()[0] if dlg.exec() and dlg.selectedFiles() else ""
        if path:
            self.settings.setValue("last_dir", os.path.dirname(path))
        return path

    def open_files(self):
        for p in self.pick_open():
            self.open_path(p)

    def open_path(self, path):
        path = os.path.abspath(path)
        for i in range(self.tabs.count()):
            if self.tabs.widget(i).path == path:
                self.tabs.setCurrentIndex(i)
                return
        try:
            with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
                text = f.read().replace("\r\n", "\n")
        except OSError as e:
            self.error("Open failed", str(e))
            return
        # replace a pristine untitled tab
        cur = self.current()
        replace = (self.tabs.count() == 1 and cur and not cur.path
                   and not cur.document().isModified() and not cur.toPlainText())
        self.new_tab(path, text, path.lower().endswith(MD_EXT))
        if replace:
            self.tabs.removeTab(0)
            cur.deleteLater()
            self.update_tabbar()

    def save(self):
        ed = self.current()
        if not ed.path:
            return self.save_as()
        return self.write(ed, ed.path)

    def save_as(self):
        ed = self.current()
        start = ed.path or ("untitled.md" if ed.markdown else "untitled.txt")
        path = self.pick_save(start)
        if not path:
            return False
        return self.write(ed, path)

    def write(self, ed, path):
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(ed.toPlainText())
        except OSError as e:
            self.error("Save failed", str(e))
            return False
        ed.path = os.path.abspath(path)
        ed.document().setModified(False)
        idx = self.tabs.indexOf(ed)
        self.tabs.setTabText(idx, os.path.basename(path))
        self.tabs.setTabToolTip(idx, ed.path)
        self.on_tab_changed(idx)
        return True

    # --- regex modules
    def open_modules(self):
        if not self.current():
            return
        dlg = ModulePicker(load_modules(), self)
        if dlg.exec() and dlg.chosen:
            self.find_bar.show_pattern(dlg.chosen)

    def edit_modules(self):
        path = modules_path()
        if not os.path.exists(path):
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(MODULES_TEMPLATE)
            except OSError as e:
                self.error("Modules file", str(e))
                return
        self.open_path(path)

    # --- modes / font
    def toggle_markdown(self, *_):
        ed = self.current()
        ed.set_markdown(not ed.markdown)
        self.md_action.setChecked(ed.markdown)
        self.md_button.setChecked(ed.markdown)

    def font_entered(self, text=None):
        text = (text if isinstance(text, str) else self.font_box.text()).strip().lower()
        match = next((f for f in QFontDatabase.families() if f.lower() == text), None)
        if match:
            self.font_box.setText(match)
            self.change_font(match)
            if self.current():
                self.current().setFocus()
        else:  # unknown name: put the current font back
            self.font_box.setText(self.font_.family())

    def change_font(self, family):
        self.settings.setValue("font_family", family)
        self.apply_font(family)

    def apply_font(self, family=None):
        self.font_ = QFont(family or self.font_.family())
        self.font_.setPointSize(self.font_size)
        self.font_.setStyleHint(QFont.StyleHint.Monospace)
        self.font_.setKerning(False)
        for i in range(self.tabs.count()):
            self.tabs.widget(i).set_editor_font(self.font_)
        self.apply_ui_font()

    def apply_ui_font(self):
        # same family as the editor, but the UI keeps its own size (UI_FONT_SIZE)
        ui = QFont(self.font_.family(), UI_FONT_SIZE)
        QApplication.setFont(ui)  # new dialogs / popups
        # With an app-wide stylesheet, Qt doesn't reliably restyle widgets that
        # already exist, so push the font onto the UI pieces directly.
        # (The editors keep their own font and are left alone.)
        self.setFont(ui)
        parts = [self.menuBar(), self.tabs.tabBar(), self.statusBar()]
        parts += self.menuBar().findChildren(QMenu)
        parts += self.statusBar().findChildren(QWidget)
        parts += [self.find_bar] + self.find_bar.findChildren(QWidget)
        for w in parts:
            w.setFont(ui)

    def set_size(self, size):
        self.font_size = max(6, min(72, size))
        self.settings.setValue("font_size", self.font_size)
        self.apply_font()

    def zoom(self, step):
        self.size_box.setValue(self.size_box.value() + step)

    def closeEvent(self, e):
        for i in range(self.tabs.count() - 1, -1, -1):
            if not self.close_tab(i):
                e.ignore()
                return
            if self.tabs.count() == 1 and not self.current().path \
                    and not self.current().toPlainText():
                continue
        e.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont(app.font().family(), UI_FONT_SIZE))
    app.setStyleSheet(STYLE)
    win = MainWindow()
    for p in sys.argv[1:]:
        if os.path.isfile(p):
            win.open_path(p)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()