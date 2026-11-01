"""The pet owns its local interaction and the canvas presentation it initiates."""
import threading
import uuid
from PySide6.QtCore import QObject, Signal, Slot, Property, QTimer
from PySide6.QtGui import QGuiApplication
from .presentation import Presentation
from .window import GuiDispatcher
from .user_access import DesktopUserAccess
from ..protocol import PlatformError


class PetBridge(QObject):
    changed = Signal()
    completed = Signal(object)
    reported = Signal(object)

    def __init__(self, pet):
        super().__init__()
        self._pet = pet
        self._notice = ''
        self._busy = False
        self._pending_input = None
        self._drag_start = None
        self._drag_context = None
        self._drag_pending = None
        self._drag_worker = False
        self._drag_finished = False
        self._lock = threading.Lock()
        self.completed.connect(self._complete)
        self.reported.connect(self._report)
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._monitor)
        self.moveToThread(QGuiApplication.instance().thread())

    @Property(str, notify=changed)
    def notice(self): return self._notice

    @Property(bool, notify=changed)
    def busy(self): return self._busy

    @Slot(object)
    def _complete(self, outcome):
        generation, error = outcome
        if generation != self._pet.generation or not self._pet.running:
            return
        self._busy = False
        self._notice = error or ''
        self.changed.emit()
        pending, self._pending_input = self._pending_input, None
        if pending and pending[2] == self._pet.generation and self._pet.running:
            self.submit(pending[0], pending[1], user_input=True)

    @Slot(object)
    def _report(self, outcome):
        generation, message = outcome
        if generation == self._pet.generation and self._pet.running:
            self._notice = message
            self.changed.emit()

    def reset(self):
        self._busy = False
        self._pending_input = None
        self._drag_start = None
        self.changed.emit()

    def submit(self, fn, context=None, user_input=False):
        if not self._pet.running: return
        if self._busy:
            if user_input:
                self._pending_input = (fn, context, self._pet.generation)
            return
        self._busy = True
        generation = self._pet.generation
        self.changed.emit()
        def work():
            error = None
            try:
                if generation == self._pet.generation and self._pet.running:
                    fn(context)
            except Exception as exc:
                error = str(exc)
            self.completed.emit((generation, error))
        threading.Thread(target=work, daemon=True, name='pet-input').start()

    @Slot()
    def activate(self):
        if self._pet.user_access is None: return
        try:
            context = self._pet.user_access.context()
            self.submit(self._pet.open_canvas, context, user_input=True)
        except Exception as exc:
            self._notice = str(exc)
            self.changed.emit()

    @Slot()
    def management(self):
        if self._pet.user_access is None: return
        try:
            context = self._pet.user_access.context()
            self.submit(lambda ctx: self._pet.port.call(self._pet.manager_id, 'show', {}, context=ctx), context, user_input=True)
        except Exception as exc:
            self._notice = str(exc)
            self.changed.emit()

    @Slot()
    def quit(self):
        QGuiApplication.instance().quit()

    @Slot(float, float)
    def beginDrag(self, x, y):
        if self._pet.user_access is None: return
        self._drag_start = (x, y, self._pet.position[0], self._pet.position[1])
        self._drag_context = self._pet.user_access.context()
        self._drag_finished = False

    @Slot(float, float)
    def dragTo(self, x, y):
        if not self._drag_start or self._drag_context is None: return
        sx, sy, px, py = self._drag_start
        with self._lock:
            self._drag_pending = (px + x - sx, py + y - sy)
            if self._drag_worker: return
            self._drag_worker = True
        context, generation = self._drag_context, self._pet.generation
        def work():
            try:
                while self._pet.running and generation == self._pet.generation:
                    with self._lock:
                        point, self._drag_pending = self._drag_pending, None
                    if point is None: break
                    self._pet.move(point, context)
            except Exception as exc:
                self.reported.emit((generation, str(exc)))
            finally:
                with self._lock:
                    self._drag_worker = False
                if self._drag_finished:
                    self._pet.save_position()
        threading.Thread(target=work, daemon=True, name='pet-drag').start()

    @Slot()
    def endDrag(self):
        self._drag_finished = True
        self._drag_start = None
        with self._lock:
            moving = self._drag_worker
        if not moving: self._pet.save_position()

    @Slot()
    def _monitor(self):
        if self._pet.has_pending_session():
            self.submit(lambda ctx: self._pet.monitor_session())


class Pet(Presentation):
    source, title, size = 'Pet.qml', 'Polaris · 桌宠', (280, 320)

    def __init__(self, runtime=None, window_id='window', cleanup_port=None,
                 canvas_id='canvas', manager_id='manager', user_access=None):
        super().__init__(runtime, window_id, cleanup_port)
        self.canvas_id, self.manager_id = canvas_id, manager_id
        self.user_access = user_access or (DesktopUserAccess(runtime) if runtime is not None else None)
        self.window_options = {'transparent': True, 'frameless': True, 'topmost': True}
        self._gui = GuiDispatcher()
        self.bridge = PetBridge(self)
        self.qt_context = {'petActions': self.bridge}
        self.generation = uuid.uuid4().hex
        self._session_lock = threading.RLock()
        self._session = None
        self._recovery = None
        self._last_window_state = None
        self._position = None
        self._data_path = None
        interaction_permissions = [
            {'target': canvas_id, 'name': 'show'}, {'target': canvas_id, 'name': 'status'},
            {'target': canvas_id, 'name': 'dismissed', 'kind': 'event'},
            {'target': manager_id, 'name': 'show'},
        ] + [{'target': window_id, 'name': name} for name in ('status', 'create', 'show', 'hide', 'update', 'move')]
        self._interaction_permissions = interaction_permissions
        self.views[0]['actions'] += [
            {'label': '展开画布', 'operation': 'open_canvas', 'permissions': interaction_permissions},
        ]
        self.operation('open_canvas', 'write')(lambda p, c: self.open_canvas(c))
        self.operation('say', 'write')(self.say)
        self.dependencies[0]['operations'].append('say')

    @property
    def position(self):
        return self._position or (0, 0)

    def start(self, port):
        super().start(port)
        for name in ('show', 'hide'):
            if not any(item['target'] == port.id and item['name'] == name for item in self._interaction_permissions):
                self._interaction_permissions.append({'target': port.id, 'name': name})
        self.generation = uuid.uuid4().hex
        if self.user_access:
            self.user_access.bind(port.id)
            directory = self.user_access.data_directory()
            if directory is not None:
                from ..persistence import read_json
                self._data_path = directory / 'position.json'
                saved = read_json(self._data_path, {})
                if isinstance(saved.get('x'), int) and isinstance(saved.get('y'), int):
                    self.window_options.update(x=saved['x'], y=saved['y'])
        self._gui.run(self.bridge.reset)
        self._gui.run(self.bridge.timer.start)

    def stop(self):
        self.generation = uuid.uuid4().hex
        self._gui.run(self.bridge.timer.stop)
        self._gui.run(self.bridge.reset)
        with self._session_lock:
            session, self._session = self._session, None
            self._recovery = None
        if session and session.get('subscription') and self.port:
            try: self.port.unsubscribe(session['subscription'])
            except PlatformError: pass
        self.save_position()
        super().stop()

    def show(self, context=None, params=None):
        result = super().show(context, params)
        self._position = (result.get('x', 0), result.get('y', 0))
        self.window_options.update(x=self._position[0], y=self._position[1])
        return result

    def status(self, context=None):
        result = super().status(context)
        with self._session_lock:
            result['activeSession'] = self._session['id'] if self._session else None
            result['waitingForWindow'] = self._recovery is not None
        return result

    def say(self, params, context):
        message = params.get('message')
        if not isinstance(message, str) or len(message) > 2000:
            raise PlatformError('invalid_params', '请输入不超过2000字的消息')
        self.properties['message'] = message
        self.show(context)
        self._window('update', {'handle': self.handle, 'properties': self.properties}, context)
        return {'shown': True}

    def move(self, point, context):
        result = self._window('move', {'handle': self.handle, 'x': point[0], 'y': point[1]}, context)
        self._position = (result['x'], result['y'])
        self.window_options.update(x=result['x'], y=result['y'])
        return result

    def save_position(self):
        if self._data_path and self._position:
            from ..persistence import write_json
            write_json(self._data_path, {'x': self._position[0], 'y': self._position[1]})

    def has_pending_session(self):
        with self._session_lock:
            return self._session is not None or self._recovery is not None

    def open_canvas(self, context):
        with self._session_lock:
            if self._session or not self.running:
                return self.status()
            session = {'id': uuid.uuid4().hex, 'generation': self.generation, 'context': context,
                       'subscription': None, 'canvasInstance': self.user_access.status(self.canvas_id)['instance']}
            self._session = session
        try:
            session['subscription'] = self.port.subscribe(self.canvas_id, 'dismissed', self._dismissed, context=context)
            result = self.port.call(self.canvas_id, 'show', {'sessionId': session['id'],
                       'anchor': {'x': self.position[0], 'y': self.position[1]}}, context=context)
            with self._session_lock:
                should_hide = self._session is session and self.running and session['generation'] == self.generation
            if should_hide:
                super().hide(context)
                with self._session_lock:
                    already_ended = self._session is not session
                if already_ended and self.running and session['generation'] == self.generation:
                    self.show(context)
            return result
        except Exception:
            self._cancel(session)
            raise

    def _cancel(self, session):
        with self._session_lock:
            if self._session is session: self._session = None
        if session.get('subscription') and self.port:
            try: self.port.unsubscribe(session['subscription'])
            except PlatformError: pass

    def _dismissed(self, payload, context):
        with self._session_lock:
            session = self._session
        if session and payload.get('sessionId') == session['id']:
            self._restore(session, context)

    def _restore(self, session, context):
        self._cancel(session)
        if not self.running or session['generation'] != self.generation:
            return
        try:
            self.show(context)
            self._recovery = None
        except PlatformError as exc:
            self._recovery = (self.generation, context)
            self._last_window_state = None
            if exc.code not in ('unavailable', 'window_unavailable', 'dependency_unavailable'):
                raise

    def monitor_session(self):
        if not self.user_access or not self.running: return
        with self._session_lock:
            session = self._session
        if session:
            status = self.user_access.status(self.canvas_id)
            window = self.user_access.status(self.window_id)
            ended = status['state'] != 'running' or status['instance'] != session['canvasInstance'] or window['state'] != 'running'
            if not ended:
                view = self.port.call(self.canvas_id, 'status', {}, context=session['context'])
                ended = view.get('sessionId') != session['id'] or not view.get('visible')
            if ended:
                self._restore(session, session['context'])
        if self._recovery:
            generation, context = self._recovery
            window = self.user_access.status(self.window_id)
            state = (window['state'], window['instance'])
            if state != self._last_window_state:
                self._last_window_state = state
                if state[0] == 'running' and generation == self.generation and self.running:
                    self._recovery = None
                    try:
                        self.show(context)
                    except Exception:
                        self._recovery = (generation, context)
                        raise


def create_pet(runtime=None, window_id='window', cleanup_port=None,
               canvas_id='canvas', manager_id='manager', user_access=None):
    return Pet(runtime, window_id, cleanup_port, canvas_id, manager_id, user_access)
