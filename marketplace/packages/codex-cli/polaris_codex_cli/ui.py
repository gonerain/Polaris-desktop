import json
from pathlib import Path
from uuid import uuid4
from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer, QUrl
from PySide6.QtQml import QQmlComponent, QQmlContext, qmlContext, qmlEngine
from shiboken6 import isValid
from polaris_platform.desktop.qt_ports import GuiDispatcher
from polaris_platform.protocol import PlatformError


class Bridge(QObject):
    changed = Signal()

    def __init__(self, component, context, local_input, parent=None):
        super().__init__(parent)
        self.component, self.context, self.local_input = component, context, local_input
        self.state = {}
        self.notice = ''
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()

    @Property(str, notify=changed)
    def stateJson(self):
        return json.dumps(dict(**self.state, notice=self.notice), ensure_ascii=False)

    @Slot()
    def refresh(self):
        try:
            self.state = self.context.call(self.component.port.id, 'get', {})
        except Exception as error:
            self.notice = str(error)
        self.changed.emit()

    @Slot(str, str, result=bool)
    def action(self, operation, params):
        try:
            self.local_input.call(operation, json.loads(params), permissions=[(self.component.port.id, operation)])
            self.notice = ''
            self.refresh()
            return True
        except Exception as error:
            self.notice = str(error)
            self.refresh()
            return False

    @Slot(str, str)
    def answer(self, ident, answer):
        try:
            request = next(r for r in self.state['requests'] if str(r['id']) == ident)
            method, params = request['method'], request['params']
            if method in ('item/commandExecution/requestApproval', 'item/fileChange/requestApproval'):
                result = {'decision': answer}
            elif method == 'item/permissions/requestApproval':
                result = {'permissions': params['permissions'] if answer == 'accept' else {}, 'scope': 'turn'}
            elif method == 'item/tool/requestUserInput':
                answers = json.loads(answer)
                result = {'answers': {question['id']: {'answers': [answers[question['id']]]} for question in params['questions']}}
            else:
                raise ValueError('不支持的 Codex 请求：' + method)
            self.local_input.call('respond', {'request_id': ident, 'result': result}, permissions=[(self.component.port.id, 'respond')])
            self.notice = ''
        except Exception as error:
            self.notice = str(error)
        self.refresh()

    def close(self):
        self.timer.stop()
        self.local_input.close()


class Presentation:
    def __init__(self, component):
        self.component, self.gui, self.views = component, GuiDispatcher(), {}

    def create(self, parent, ctx):
        local_input = ctx.local_view_input(parent)
        def mount():
            engine = qmlEngine(parent)
            scope = QQmlContext(qmlContext(parent), parent)
            bridge = Bridge(self.component, ctx, local_input, scope)
            scope.setContextProperty('codexBridge', bridge)
            definition = QQmlComponent(engine, QUrl.fromLocalFile(str(Path(__file__).with_name('Codex.qml'))))
            item = definition.create(scope)
            if item is None:
                bridge.close()
                raise PlatformError('view_error', '; '.join(error.toString() for error in definition.errors()))
            scope.setParent(item); definition.setParent(item)
            item.setParent(parent); item.setParentItem(parent)
            local_input.bind(item)
            handle = uuid4().hex
            self.views[handle] = (item, bridge)
            item.destroyed.connect(lambda: (bridge.close(), self.views.pop(handle, None)))
            return {'handle': handle, 'item': item}
        return self.gui.run(mount)

    def release(self, handle):
        def dispose():
            resource = self.views.pop(handle, None)
            if resource:
                item, bridge = resource
                bridge.close()
                if isValid(item):
                    item.setVisible(False); item.setParentItem(None); item.deleteLater()
            return {'released': bool(resource)}
        return self.gui.run(dispose)

    def close(self):
        for handle in tuple(self.views): self.release(handle)
