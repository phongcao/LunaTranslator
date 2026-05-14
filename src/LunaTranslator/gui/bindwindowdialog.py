from qtsymbols import *
import os
import windows, qtawesome, gobject
from NativeUtils import GetProcessFirstWindow
from myutils.config import globalconfig, _TR
from myutils.wrapper import Singleton
from myutils.hwnd import ListProcess, mouseselectwindow, getExeIcon
from gui.usefulwidget import saveposwindow
from gui.dynalang import LPushButton, LLabel


@Singleton
class BindWindowDialog(saveposwindow):

    setcurrentpidpnamesignal = pyqtSignal(int, int)

    def selectwindowcallback(self, pid, hwnd):
        if pid == os.getpid() or not hwnd:
            return mouseselectwindow(self.setcurrentpidpnamesignal.emit)
        self.setEnabled(True)
        self.button.setText("点击此按钮后点击游戏窗口")
        name = windows.GetProcessFileName(pid) or ""
        if name:
            pids = ListProcess(name)
            if not pids:
                pids = [pid]
        else:
            pids = [pid]
        self.processEdit.setText(name)
        self.processIdEdit.setText(",".join([str(process_id) for process_id in pids]))
        self.windowtext.setText(windows.GetWindowText(hwnd))
        self.processEdit.setCursorPosition(0)
        self.processIdEdit.setCursorPosition(0)
        self.windowtext.setCursorPosition(0)
        self.selectedp = (pids, name, hwnd)

    def closeEvent(self, e):
        gobject.base.BindWindowDialog = None
        super().closeEvent(e)

    def __init__(self, parent, callback):
        super().__init__(
            parent,
            poslist=globalconfig["attachprocessgeo"],
            flags=Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setcurrentpidpnamesignal.connect(self.selectwindowcallback)

        self.iconcache = {}

        self.callback = callback
        self.selectedp = None
        self.setWindowTitle(_TR("绑定窗口"))
        self.setWindowIcon(
            qtawesome.icon(globalconfig["toolbutton"]["buttons"]["bindwindow"]["icon"])
        )
        w = QWidget()
        self.layout1 = QVBoxLayout(w)

        class __LPushButton(LPushButton):
            def sizeHint(self):
                size = super().sizeHint()
                return QSize(size.width(), 2 * size.height())

        self.button = __LPushButton("点击此按钮后点击游戏窗口")
        self.button.setCheckable(True)
        self.button.setStyleSheet("font-weight: bold;")
        self.button.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.button.clicked.connect(
            lambda: (
                self.button.setText("请点击游戏窗口"),
                self.setEnabled(False),
                mouseselectwindow(self.setcurrentpidpnamesignal.emit),
            )
        )
        self.layout1.addWidget(
            LLabel(
                "如果没看见想要附加的进程，可以尝试点击下方按钮后点击游戏窗口,或者尝试使用管理员权限运行本软件"
            )
        )
        self.layout1.addWidget(self.button)
        self.layout2 = QHBoxLayout()
        self.processIdEdit = QLineEdit()
        self.layout2.addWidget(LLabel(("进程号")))
        self.layout2.addWidget(self.processIdEdit)
        self.processEdit = QLineEdit()
        self.layout3 = QHBoxLayout()
        self.layout3.addWidget(LLabel(("程序名")))
        self.layout3.addWidget(self.processEdit)

        self.windowtext = QLineEdit()
        self.layout2.addWidget(LLabel(("标题")))
        self.layout2.addWidget(self.windowtext)
        self.processList = QListView()
        self.currentChanged_Ori = self.processList.currentChanged
        self.processList.currentChanged = self.__change
        self.buttonBox = QDialogButtonBox()
        self.buttonBox.setStandardButtons(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.layout1.addLayout(self.layout2)
        self.layout1.addLayout(self.layout3)
        self.layout1.addWidget(self.processList)
        bottomlayout = QHBoxLayout()
        refreshbutton = LPushButton("刷新")
        refreshbutton.clicked.connect(self.refreshfunction)
        bottomlayout.addWidget(refreshbutton)
        bottomlayout.addStretch(1)
        bottomlayout.addWidget(self.buttonBox)

        self.layout1.addLayout(bottomlayout)
        self.setCentralWidget(w)

        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.close)
        self.processIdEdit.textEdited.connect(self.editpid)
        self.processIdEdit.setValidator(
            QRegularExpressionValidator(QRegularExpression("([0-9]+,)*"))
        )
        self.processEdit.textEdited.connect(self.filterproc)

    def filterproc(self):
        self.processIdEdit.clear()
        self.windowtext.clear()
        text = self.processEdit.text()
        if len(text) == 0:
            self.refreshfunction()
            return
        for row in range(self.model.rowCount()):
            hide = not (text in self.model.item(row, 0).text())
            self.processList.setRowHidden(row, hide)

    def refreshfunction(self):

        self.windowtext.clear()
        self.processEdit.clear()
        self.processIdEdit.clear()
        self.selectedp = None

        self.model = QStandardItemModel(self.processList)
        self.processlist = {}
        self.processList.setModel(self.model)
        for pexe, pids in ListProcess().items():
            hwnd = self.guesshwnd(pids)
            if not hwnd:
                continue
            self.processlist[pexe] = (pids, hwnd)
            if pexe in self.iconcache:
                icon = self.iconcache[pexe]
            else:
                icon = getExeIcon(pexe)
                if icon.isNull():
                    img = QPixmap(QSize(100, 100))
                    img.fill(Qt.GlobalColor.transparent)
                    icon = QIcon(img)
                self.iconcache[pexe] = icon
            item = QStandardItem(icon, pexe)
            item.setEditable(False)
            self.model.appendRow(item)

    def showEvent(self, e):
        self.refreshfunction()
        return super().showEvent(e)

    def safesplit(self, process):
        try:
            return list(set([int(_) for _ in process.split(",")]))
        except:
            return []

    def editpid(self, process):
        pids = self.safesplit(process)
        if len(pids) == 0:
            self.windowtext.clear()
            self.processEdit.clear()
            self.selectedp = None
            return
        hwnd = self.guesshwnd(pids)
        self.selectedp = (
            pids,
            windows.GetProcessFileName(pids[0]) or "",
            hwnd,
        )
        self.windowtext.setText(windows.GetWindowText(hwnd) if hwnd else "")
        self.processEdit.setText(self.selectedp[1])
        self.windowtext.setCursorPosition(0)
        self.processEdit.setCursorPosition(0)

    def __change(self, index: QModelIndex, __):
        if not (index and index.isValid()):
            return self.currentChanged_Ori(index, __)
        self.processList.scrollTo(index)
        pexe = self.model.itemFromIndex(index).text()
        pids, hwnd = self.processlist.get(pexe, ([], 0))
        self.processEdit.setText(pexe)
        self.processIdEdit.setText(",".join([str(process_id) for process_id in pids]))
        self.selectedp = (pids, pexe, hwnd)
        self.windowtext.setText(windows.GetWindowText(hwnd))
        self.processEdit.setCursorPosition(0)
        self.processIdEdit.setCursorPosition(0)
        self.windowtext.setCursorPosition(0)
        return self.currentChanged_Ori(index, __)

    def guesshwnd(self, pids):
        for pid in pids:
            hwnd = GetProcessFirstWindow(pid)
            if hwnd != 0:
                return hwnd
        return 0

    def accept(self):
        if self.selectedp is None or not self.selectedp[-1]:
            self.close()
            return
        self.close()
        self.callback(self.selectedp)