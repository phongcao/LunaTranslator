from qtsymbols import *
from collections import OrderedDict
import html
import time
import windows, NativeUtils, gobject
from myutils.config import globalconfig
from myutils.hwnd import safepixmap
from gui.dynalang import LAction
from traceback import print_exc


class SideGrip(QWidget):
    def __init__(self, parent, edge):
        QWidget.__init__(self, parent)
        if edge == Qt.Edge.LeftEdge:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            self.resizeFunc = self.resizeLeft
        elif edge == Qt.Edge.TopEdge:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
            self.resizeFunc = self.resizeTop
        elif edge == Qt.Edge.RightEdge:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            self.resizeFunc = self.resizeRight
        else:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
            self.resizeFunc = self.resizeBottom
        self.mousePos = None

    def resizeLeft(self, delta):
        window = self.window()
        width = max(window.minimumWidth(), window.width() - delta.x())
        geo = window.geometry()
        geo.setLeft(geo.right() - width)
        window.setGeometry(geo)

    def resizeTop(self, delta):
        window = self.window()
        height = max(window.minimumHeight(), window.height() - delta.y())
        geo = window.geometry()
        geo.setTop(geo.bottom() - height)
        window.setGeometry(geo)

    def resizeRight(self, delta):
        window = self.window()
        width = max(window.minimumWidth(), window.width() + delta.x())
        window.resize(width, window.height())

    def resizeBottom(self, delta):
        window = self.window()
        height = max(window.minimumHeight(), window.height() + delta.y())
        window.resize(window.width(), height)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.mousePos = event.pos()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.mousePos is not None:
            delta = event.pos() - self.mousePos
            self.resizeFunc(delta)

    def mouseReleaseEvent(self, _):
        self.mousePos = None


class Mainw(QMainWindow):
    _gripSize = 8

    def __init__(self, x):
        QMainWindow.__init__(self, x)

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | self.windowFlags())

        self.sideGrips = [
            SideGrip(self, Qt.Edge.LeftEdge),
            SideGrip(self, Qt.Edge.TopEdge),
            SideGrip(self, Qt.Edge.RightEdge),
            SideGrip(self, Qt.Edge.BottomEdge),
        ]
        # corner grips should be "on top" of everything, otherwise the side grips
        # will take precedence on mouse events, so we are adding them *after*;
        # alternatively, widget.raise_() can be used
        self.cornerGrips = [QSizeGrip(self) for i in range(4)]
        for s in self.cornerGrips:
            s.setStyleSheet("background-color: transparent;")

    @property
    def gripSize(self):
        return self._gripSize

    def setGripSize(self, size):
        if size == self._gripSize:
            return
        self._gripSize = max(2, size)
        self.updateGrips()

    def updateGrips(self):
        self.setContentsMargins(*[self.gripSize] * 4)

        outRect = self.rect()
        # an "inner" rect used for reference to set the geometries of size grips
        inRect = outRect.adjusted(
            self.gripSize, self.gripSize, -self.gripSize, -self.gripSize
        )

        # top left
        self.cornerGrips[0].setGeometry(QRect(outRect.topLeft(), inRect.topLeft()))
        # top right
        self.cornerGrips[1].setGeometry(
            QRect(outRect.topRight(), inRect.topRight()).normalized()
        )
        # bottom right
        self.cornerGrips[2].setGeometry(
            QRect(inRect.bottomRight(), outRect.bottomRight())
        )
        # bottom left
        self.cornerGrips[3].setGeometry(
            QRect(outRect.bottomLeft(), inRect.bottomLeft()).normalized()
        )

        # left edge
        self.sideGrips[0].setGeometry(0, inRect.top(), self.gripSize, inRect.height())
        # top edge
        self.sideGrips[1].setGeometry(inRect.left(), 0, inRect.width(), self.gripSize)
        # right edge
        self.sideGrips[2].setGeometry(
            inRect.left() + inRect.width(), inRect.top(), self.gripSize, inRect.height()
        )
        # bottom edge
        self.sideGrips[3].setGeometry(
            self.gripSize, inRect.top() + inRect.height(), inRect.width(), self.gripSize
        )

    def resizeEvent(self, event):
        QMainWindow.resizeEvent(self, event)
        self.updateGrips()


class OCRRegionTextEdit(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFrameStyle(0)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Base, Qt.GlobalColor.transparent)
        self.setPalette(pal)
        self.document().setDocumentMargin(0)
        self.applystyle()

    def applystyle(self):
        opacity = max(0, min(100, int(globalconfig.get("ocr_overlay_opacity", 88))))
        background_alpha = int(round(255 * opacity / 100))
        border_alpha = int(round(32 * opacity / 100))
        self.setStyleSheet(
            "background-color: rgba(0, 0, 0, %s);"
            "border-radius: 4px;"
            "border: 1px solid rgba(255, 255, 255, %s);"
            "padding: 6px;"
            % (background_alpha, border_alpha)
        )


class OCRRegionTextOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.text = OCRRegionTextEdit(self)
        self.text.setGeometry(0, 0, 1, 1)
        self._applytransparentstate()

    def _applytransparentstate(self):
        style = windows.GetWindowLong(int(self.winId()), windows.GWL_EXSTYLE)
        style |= windows.WS_EX_TRANSPARENT
        windows.SetWindowLong(int(self.winId()), windows.GWL_EXSTYLE, style)

    def showEvent(self, event):
        self._applytransparentstate()
        super().showEvent(event)


class rangeadjust(Mainw):
    closesignal = pyqtSignal()
    traceoffsetsignal = pyqtSignal(QPoint)

    @property
    def isfocus(self):
        return self.__isfocus

    @isfocus.setter
    def isfocus(self, f):
        def cleanother():
            for r in self.ranges:
                range_ui: "rangeadjust" = r.range_ui
                if range_ui != self:
                    if range_ui.__isfocus:
                        range_ui.__isfocus = False
                        range_ui.setstyle()

        if sum(not (r.range_ui._rect is None) for r in self.ranges) > 1:
            if f:
                cleanother()
                self.__isfocus = True
            else:
                self.__isfocus = False
        else:
            cleanother()
            self.__isfocus = False
        self.setstyle()

    def mouseDoubleClickEvent(self, a0):
        self.isfocus = not self.isfocus
        gobject.base.translation_ui.startTranslater()
        return super().mouseDoubleClickEvent(a0)

    def starttrace(self, pos):
        self.tracepos = self.geometry().topLeft()
        self.traceposstart = pos

    def traceoffset(self, curr: QPoint):
        hwnd = gobject.base.hwnd
        if not hwnd:
            self.tracepos = QPoint()
            return
        if windows.MonitorFromWindow(hwnd) != windows.MonitorFromWindow(
            int(self.winId())
        ):
            self.tracepos = QPoint()
            return
        keystate = windows.GetKeyState(windows.VK_LBUTTON)
        if keystate < 0 and windows.GetForegroundWindow() == int(self.winId()):
            self.tracepos = QPoint()
            return
        if self._isTracking:
            self.tracepos = QPoint()
            return
        _geo = self.geometry()
        if self.tracepos.isNull():
            self.tracepos = _geo.topLeft()
            self.traceposstart = curr
        target = self.tracepos + (curr - self.traceposstart) * self.devicePixelRatioF()
        self.setGeometry(
            target.x(),
            target.y(),
            _geo.width(),
            _geo.height(),
        )

    def rect(self):
        geo = self.geometry()
        return QRectF(
            0,
            0,
            geo.width() / self.devicePixelRatioF(),
            geo.height() / self.devicePixelRatioF(),
        ).toRect()

    def __init__(self, parent, ranges):
        self._rect = None
        self.tracepos = QPoint()
        self._isTracking = False
        self.__suspend_rect_sync = 0
        self.label = None
        self.drag_label = None
        self.translation_overlay = None
        self.translation_label = None
        super().__init__(parent)
        self.__isfocus = False
        self.__rangevisible = True
        self.__manual_mouse_transparent = False
        self.__capture_suppressed = False
        self.__translation_cycle = None
        self.__translation_entries: "OrderedDict[str, dict]" = OrderedDict()
        self.__last_translation_time = 0.0
        self.__autohide_active = False
        self.__source_text_visible_getter = None
        self.ranges: list = ranges
        self.traceoffsetsignal.connect(self.traceoffset)
        self.label = QLabel(self)
        self.translation_overlay = OCRRegionTextOverlay(self)
        self.translation_label = self.translation_overlay.text
        self.translation_overlay.hide()
        self.__autohide_timer = QTimer(self)
        self.__autohide_timer.setInterval(500)
        self.__autohide_timer.timeout.connect(self.__check_autohide)
        self.__autohide_timer.start()
        self.setstyle()
        self.closesignal.connect(self.close)
        self.drag_label = QLabel(self)
        self.drag_label.setGeometry(0, 0, 4000, 2000)
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.showmenu)
        self.drag_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        for s in self.cornerGrips:
            s.raise_()
        gobject.base.show_fany_switch.connect(self.onshowfanyswitch)
        self.onshowfanyswitch(globalconfig["showfanyi"])

    def onshowfanyswitch(self, _):
        self.refreshtranslation()

    def _windowratio(self):
        try:
            ratio = NativeUtils.GetDevicePixelRatioF(int(self.winId()))
        except:
            ratio = 0
        if not ratio:
            ratio = self.devicePixelRatioF()
        return ratio or 1

    def _suspendrectsync(self):
        self.__suspend_rect_sync += 1
        QTimer.singleShot(0, self._resumerectsync)

    def _resumerectsync(self):
        if self.__suspend_rect_sync:
            self.__suspend_rect_sync -= 1

    def _applytransparentstate(self):
        transparent = (not self.__rangevisible) or self.__manual_mouse_transparent
        style = windows.GetWindowLong(int(self.winId()), windows.GWL_EXSTYLE)
        if transparent:
            style |= windows.WS_EX_TRANSPARENT
        else:
            style &= ~windows.WS_EX_TRANSPARENT
        windows.SetWindowLong(int(self.winId()), windows.GWL_EXSTYLE, style)

    def _updateinteractivemask(self):
        if not self.__rangevisible:
            self.clearMask()
            return
        outer = self.rect()
        if outer.isEmpty():
            return
        inner = outer.adjusted(
            self.gripSize,
            self.gripSize,
            -self.gripSize,
            -self.gripSize,
        )
        if inner.width() <= 0 or inner.height() <= 0:
            self.setMask(QRegion(outer))
            return
        self.setMask(QRegion(outer).subtracted(QRegion(inner)))

    def setrangevisible(self, visible: bool):
        self._suspendrectsync()
        self.__rangevisible = visible
        self.label.setVisible(visible)
        self.drag_label.setVisible(visible)
        for grip in self.sideGrips + self.cornerGrips:
            grip.setVisible(visible)
        self._updateinteractivemask()
        self._applytransparentstate()
        self.refreshtranslation()

    def _buildtranslationhtml(self, fontsize: float):
        fontfamily = html.escape(globalconfig["fonttype2"])
        fontweight = "bold" if globalconfig.get("showbold_trans", False) else "normal"
        textcolor = "#FFFFFF"
        namecolor = "#D9DDE3"
        blocks = []
        for item in self.__translation_entries.values():
            name = item["name"]
            text = item["text"]
            if globalconfig.get("showfanyisource", False) and name:
                blocks.append(
                    '<div style="color:{color}; font-weight:{weight}; margin-bottom:2px;">{name}</div>'.format(
                        color=namecolor,
                        weight=fontweight,
                        name=html.escape(name),
                    )
                )
            blocks.append(
                '<div style="color:{color}; white-space:pre-wrap;">{text}</div>'.format(
                    color=textcolor,
                    text=html.escape(text).replace("\n", "<br>"),
                )
            )
        return (
            '<div style="font-family:\'{fontfamily}\'; font-size:{fontsize}pt; font-weight:{weight};">{body}</div>'.format(
                fontfamily=fontfamily,
                fontsize=fontsize,
                weight=fontweight,
                body="<div style=\"height:6px;\"></div>".join(blocks),
            )
        )

    def _fittranslationfontsize(self, width: int, height: int):
        if width <= 0 or height <= 0:
            return globalconfig["fontsize"]
        low = 4
        high = max(int(globalconfig["fontsize"]), 4)
        high = max(high, min(int(height), 72))
        best = low
        document = QTextDocument(self.translation_label)
        while low <= high:
            mid = (low + high) // 2
            document.setHtml(self._buildtranslationhtml(mid))
            document.setTextWidth(max(1, width - 12))
            if document.size().height() <= height - 12:
                best = mid
                low = mid + 1
            else:
                high = mid - 1
        return best

    def _refreshwindowvisible(self):
        should_show = bool(self._rect) and self.__rangevisible
        if should_show:
            self.show()
        else:
            self.hide()
        self._applytransparentstate()

    def refreshtranslation(self):
        if (self.translation_overlay is None) or (self.translation_label is None):
            return
        show_translation = (
            globalconfig["showfanyi"]
            and bool(self.__translation_entries)
            and (not self.__capture_suppressed)
            and (not self.__autohide_active)
        )
        if show_translation:
            margin = self.gripSize if self.__rangevisible else 0
            width = max(1, self.width() - 2 * margin)
            height = max(1, self.height() - 2 * margin)
            geo = self.geometry()
            ratio = self.devicePixelRatioF() or 1
            self.translation_overlay.setGeometry(
                int(geo.x() / ratio) + margin,
                int(geo.y() / ratio) + margin,
                width,
                height,
            )
            self.translation_label.setGeometry(0, 0, width, height)
            fontsize = self._fittranslationfontsize(width, height)
            self.translation_label.setHtml(self._buildtranslationhtml(fontsize))
            self.translation_overlay.show()
            self.translation_overlay.raise_()
        else:
            self.translation_overlay.hide()
        for grip in self.cornerGrips:
            grip.raise_()
        self._refreshwindowvisible()

    def setcapturesuppressed(self, suppressed: bool):
        if self.__capture_suppressed == suppressed:
            return
        self.__capture_suppressed = suppressed
        self.refreshtranslation()

    def setsourcetextvisiblegetter(self, getter):
        self.__source_text_visible_getter = getter

    def _currentsourcetextvisible(self):
        if not self.__source_text_visible_getter:
            return False
        try:
            return bool(self.__source_text_visible_getter())
        except:
            return False

    def __check_autohide(self):
        if not globalconfig.get("ocr_overlay_autohide", False):
            if self.__autohide_active:
                self.__autohide_active = False
                self.refreshtranslation()
            return
        if not self.__translation_entries:
            return
        if self._currentsourcetextvisible():
            if self.__autohide_active:
                self.__autohide_active = False
                self.refreshtranslation()
            return
        delay = globalconfig.get("ocr_overlay_autohide_delay", 5)
        should_hide = (
            self.__last_translation_time > 0
            and time.time() - self.__last_translation_time >= delay
        )
        if should_hide != self.__autohide_active:
            self.__autohide_active = should_hide
            self.refreshtranslation()

    def begintranslationcycle(self, cycle_id: str):
        self.__translation_cycle = cycle_id

    def updatetranslation(
        self, cycle_id: str, engine: str, name: str, text: str, color: str
    ):
        if cycle_id != self.__translation_cycle:
            return
        if text:
            self.__translation_entries[engine] = dict(
                name=name,
                text=text,
                color=color,
            )
        else:
            self.__translation_entries.pop(engine, None)
        self.__last_translation_time = time.time()
        self.__autohide_active = False
        self.refreshtranslation()

    def cleartranslation(self):
        self.__translation_cycle = None
        self.__translation_entries.clear()
        self.refreshtranslation()

    def showmenu(self, _):
        menu = QMenu(self)
        close = LAction("关闭", menu)
        mousetransp = LAction("鼠标穿透窗口", menu)
        menu.addAction(mousetransp)
        menu.addAction(close)
        action = menu.exec(QCursor.pos())
        if action == mousetransp:
            self.__manual_mouse_transparent = not self.__manual_mouse_transparent
            self._applytransparentstate()
        elif action == close:
            self._rect = None
            self.isfocus = False
            self.cleartranslation()
            self.close()

    def setstyle(self):
        self.label.setStyleSheet(
            " border:%spx solid %s; background-color: rgba(0,0,0, %s); border-radius:0;"
            % (
                globalconfig.get("ocrrangewidth", 2),
                "red" if self.isfocus else globalconfig["ocrrangecolor"],
                1 / 255,
            )
        )
        self.translation_label.applystyle()

    def mouseMoveEvent(self, e: QMouseEvent):
        if not self.__rangevisible:
            return
        if self._isTracking:
            self._endPos = e.pos() - self._startPos
            _geo = self.geometry()
            _geo.translate(self._endPos)
            self.setGeometry(*_geo.getRect())

    def mousePressEvent(self, e: QMouseEvent):
        if not self.__rangevisible:
            return
        if e.button() == Qt.MouseButton.LeftButton:
            self._isTracking = True
            self._startPos = QPoint(e.pos().x(), e.pos().y())

    def mouseReleaseEvent(self, e: QMouseEvent):
        if not self.__rangevisible:
            return
        if e.button() == Qt.MouseButton.LeftButton:
            self._isTracking = False
            self._startPos = None
            self._endPos = None

    def rectoffset(self, rect: QRect):
        r = self.devicePixelRatioF()
        r = int(globalconfig.get("ocrrangewidth", 2) * r)
        _ = [(rect.left() + r, rect.top() + r), (rect.right() - r, rect.bottom() - r)]
        return _

    def setGeometry(self, x, y, w, h):
        ratio = self._windowratio()
        QMainWindow.setGeometry(
            self,
            int(round(x / ratio)),
            int(round(y / ratio)),
            int(round(w / ratio)),
            int(round(h / ratio)),
        )
        windows.MoveWindow(
            int(self.winId()),
            int(round(x)),
            int(round(y)),
            int(round(w)),
            int(round(h)),
            True,
        )

    def geometry(self):
        rect = windows.GetWindowRect(int(self.winId()))
        return QRect(rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1])

    def moveEvent(self, _):
        if self._rect and (not self.__suspend_rect_sync):
            self._rect = self.rectoffset(self.geometry())
        self.refreshtranslation()

    def enterEvent(self, _):
        if not self.__rangevisible:
            return
        self.drag_label.setStyleSheet("background-color:rgba(0,0,0, 0.1)")

    def leaveEvent(self, _):
        if not self.__rangevisible:
            return
        self.drag_label.setStyleSheet("background-color:none")

    def resizeEvent(self, a0):
        if self.label is None:
            return super().resizeEvent(a0)

        self.label.setGeometry(0, 0, self.width(), self.height())
        self._updateinteractivemask()
        if self._rect and (not self.__suspend_rect_sync):
            self._rect = self.rectoffset(self.geometry())
        self.refreshtranslation()
        super().resizeEvent(a0)

    def closeEvent(self, event):
        if self.translation_overlay is not None:
            self.translation_overlay.close()
        super().closeEvent(event)

    def getrect(self):
        return self._rect

    def setrect(self, rect):
        self.tracepos = QPoint()
        if rect:
            (x1, y1), (x2, y2) = rect
            r = self.devicePixelRatioF()
            self._suspendrectsync()
            self.setGeometry(
                x1 - int(globalconfig.get("ocrrangewidth", 2) * r),
                y1 - int(globalconfig.get("ocrrangewidth", 2) * r),
                x2 - x1 + int(2 * globalconfig.get("ocrrangewidth", 2) * r),
                y2 - y1 + int(2 * globalconfig.get("ocrrangewidth", 2) * r),
            )
        self._rect = rect
        self.refreshtranslation()
        # 由于使用movewindow而非qt函数，导致内部执行绪有问题。


def rangeselct_function(callback):
    p = gobject.base.translation_ui
    p = p.winid if p.isVisible() else None
    color = QColor(globalconfig["ocrrangecolor"])

    called = []

    def __cb(x1, y1, x2, y2, xoff, yoff, ptr, size):
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)
        pix = safepixmap(ptr[:size]).copy(x1, y1, x2 - x1, y2 - y1).toImage()
        callback(((x1 + xoff, y1 + yoff), (x2 + xoff, y2 + yoff)), pix)
        called.append(0)

    cb = NativeUtils.CreateSelectRangeWindow_CB(__cb)
    NativeUtils.CreateSelectRangeWindow(
        p,
        globalconfig.get("ocrselectalpha", 0.3),
        color.red(),
        color.green(),
        color.blue(),
        globalconfig.get("ocrrangewidth", 2),
        cb,
    )
    if not called:
        callback(((0, 0), (0, 0)), None)
