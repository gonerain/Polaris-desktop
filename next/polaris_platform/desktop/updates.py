"""Application-owned update window, independent of component lifecycle."""
from pathlib import Path
import shlex
import threading

from PySide6.QtCore import QObject, Signal, Slot, Property, QUrl, QStandardPaths
from PySide6.QtGui import QDesktopServices
from PySide6.QtQuick import QQuickView

from ..metadata import VERSION
from ..updates import check_release, download_release


class UpdateController(QObject):
    changed = Signal()
    completed = Signal(object)
    progressed = Signal(int)

    def __init__(self, app):
        super().__init__(app)
        self._message = f'当前版本 v{VERSION}'
        self._busy, self._progress = False, 0
        self._release = self._download = None
        self._view = None
        self.completed.connect(self._complete)
        self.progressed.connect(self._set_progress)

    @Property(str, notify=changed)
    def message(self): return self._message

    @Property(bool, notify=changed)
    def busy(self): return self._busy

    @Property(int, notify=changed)
    def progress(self): return self._progress

    @Property(bool, notify=changed)
    def canDownload(self): return self._release is not None and self._download is None

    @Property(bool, notify=changed)
    def canInstall(self): return self._download is not None

    @Property(str, notify=changed)
    def installCommand(self):
        return shlex.join(['sudo', 'apt', 'install', str(self._download)]) if self._download else ''

    @Slot()
    def show(self):
        if self._view is None:
            self._view = QQuickView()
            self._view.setTitle('Polaris · 软件更新')
            self._view.setResizeMode(QQuickView.SizeRootObjectToView)
            self._view.rootContext().setContextProperty('updates', self)
            self._view.setSource(QUrl.fromLocalFile(str(Path(__file__).with_name('Updates.qml'))))
            self._view.resize(500, 340)
        self._view.show()
        self._view.raise_()
        self._view.requestActivate()

    def _work(self, action, fn, silent=False):
        if self._busy: return
        self._busy = True
        self._progress = 0
        self._message = '正在检查 GitHub Release…' if action == 'check' else '正在下载更新包…'
        self.changed.emit()
        def work():
            try:
                result = (action, fn(), '', silent)
            except Exception as error:
                result = (action, None, str(error), silent)
            self.completed.emit(result)
        threading.Thread(target=work, daemon=True, name='polaris-update').start()

    @Slot()
    def check(self):
        if self._busy: return
        self._release = self._download = None
        self._work('check', check_release)

    def check_on_startup(self):
        self._work('check', check_release, silent=True)

    @Slot()
    def download(self):
        if self._release is None: return
        cache = QStandardPaths.writableLocation(QStandardPaths.CacheLocation)
        self._work('download', lambda: download_release(self._release, Path(cache) / 'updates', self.progressed.emit))

    @Slot(int)
    def _set_progress(self, value):
        self._progress = value
        self.changed.emit()

    @Slot(object)
    def _complete(self, outcome):
        action, result, error, silent = outcome
        self._busy = False
        if error:
            self._message = '更新失败：' + error
        elif action == 'check':
            self._release = result
            self._message = f'发现新版本 v{result.version}（当前 v{VERSION}）' if result else f'当前 v{VERSION} 已是最新正式版本'
            if result and silent: self.show()
        else:
            self._download = result
            self._message = '下载完成，SHA-256 校验通过。请打开系统安装器；安装完成后退出并重新启动 Polaris。'
        self.changed.emit()

    @Slot()
    def install(self):
        if self._download and not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._download))):
            self._message = f'无法打开系统安装器。请在终端执行：sudo apt install "{self._download}"'
            self.changed.emit()

    @Slot()
    def openFolder(self):
        if self._download:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._download.parent)))

    @Slot()
    def releases(self):
        QDesktopServices.openUrl(QUrl('https://github.com/gonerain/Polaris-desktop/releases'))
