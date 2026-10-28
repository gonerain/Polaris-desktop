"""Keep the floating window inside its screen's usable (logical-pixel) area."""
from PySide6.QtCore import QObject, QRect, QTimer, Qt
from PySide6.QtGui import QGuiApplication


class WindowBounds(QObject):
    def __init__(self, window):
        super().__init__(window)
        self._window = window
        self._screen = None
        self._presenter = window.findChild(QObject, "focusPresenter")
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(120)
        self._settle.timeout.connect(self.fit)
        for signal in (window.xChanged, window.yChanged, window.widthChanged, window.heightChanged):
            signal.connect(self._schedule)
        # Fit state-driven changes immediately, but do not fight a live drag or morph.
        window.applyingStateChanged.connect(self.fit)
        window.movingChanged.connect(self.fit)
        self._presenter.transitioningChanged.connect(self.fit)
        window.screenChanged.connect(self._screen_changed)
        self._screen_changed(window.screen())

    def _schedule(self, *_):
        self._settle.start()

    def _screen_changed(self, screen):
        if self._screen is not None:
            self._screen.availableGeometryChanged.disconnect(self._area_changed)
        self._screen = screen or QGuiApplication.primaryScreen()
        if self._screen is not None:
            self._screen.availableGeometryChanged.connect(self._area_changed)
        self._area_changed()

    def _area_changed(self, *_):
        if self._screen is not None:
            self._window.setProperty("availableGeometry", self._screen.availableGeometry())
            self.fit()

    def fit(self):
        window = self._window
        if (window.property("applyingState") or window.property("moving")
                or self._presenter.property("transitioning")):
            return
        # Native moving/resizing can take over the Qt pointer grab. Wait for
        # release even if the DragHandler has already become inactive.
        if QGuiApplication.mouseButtons() & Qt.MouseButton.LeftButton:
            self._settle.start()
            return
        area = window.property("availableGeometry").toRect()
        if area.width() <= 0 or area.height() <= 0:
            return
        width = min(window.width(), area.width())
        height = min(window.height(), area.height())
        x = max(area.x(), min(window.x(), area.x() + area.width() - width))
        y = max(area.y(), min(window.y(), area.y() + area.height() - height))
        geometry = QRect(x, y, width, height)
        if not window.property("windowPositioningSupported"):
            # A Wayland compositor owns placement, even when Qt reports x/y.
            # Repeated setGeometry() calls would fight it and log warnings.
            if window.width() != width or window.height() != height:
                window.resize(width, height)
        elif window.geometry() != geometry:
            window.setGeometry(geometry)
