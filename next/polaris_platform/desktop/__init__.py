"""Optional Qt Quick desktop components and trusted local management UI."""
from .components import GuiDispatcher, WindowHost, Canvas, Pet, create_window, create_canvas, create_pet
from .user_access import DesktopUserAccess
from .manager import Manager, create_manager


def run(runtime):
    """Launch the optional desktop against an existing platform runtime."""
    import sys
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    from pathlib import Path
    from ..bootstrap import load_factory
    definitions = [
        ('window', '窗口承载', 'create_window', {'runtime': {'runtime': True}}),
        ('canvas', '画布', 'create_canvas', {'runtime': {'runtime': True}, 'window_id': 'window'}),
        ('pet', '桌宠', 'create_pet', {'runtime': {'runtime': True}, 'window_id': 'window'}),
        ('manager', '组件管理', 'create_manager', {'runtime': {'runtime': True}}),
    ]
    installed = {item['id']: item for item in runtime.snapshot()}
    saved = {item['manifest']['id']: item for item in runtime.export_installations()}
    for identity, name, factory, kwargs in definitions:
        if identity not in installed:
            manifest = {'id': identity, 'name': name, 'version': '0.1.0', 'platformApi': 1,
                        'entry': {'mode': 'inprocess', 'factory': 'polaris_platform.desktop:' + factory,
                                  'defer': 'desktop', 'kwargs': kwargs}}
            runtime.install(manifest, load_factory(manifest, Path.cwd(), runtime, trusted_bindings=True), trusted_bindings=True)
        if identity not in installed or identity in ('window', 'manager') or saved[identity]['autostart']:
            runtime.start_component(identity)
    host = runtime.component_instance('window')
    manager = runtime.component_instance('manager')
    # These are the precise, installed capabilities of the default local interaction.
    # Existing installations retain every user revocation and never gain new items here.
    pet_is_new = 'pet' not in installed
    defaults = [('pet', 'show', 'operation'), ('pet', 'hide', 'operation'),
                ('canvas', 'show', 'operation'), ('canvas', 'status', 'operation'), ('canvas', 'dismissed', 'event'),
                ('manager', 'show', 'operation')]
    defaults += [('window', name, 'operation') for name in ('status', 'create', 'show', 'hide', 'update', 'move')]
    if pet_is_new:
        for target, name, kind in defaults:
            runtime.grant('pet', target, name, kind=kind)
    pet = runtime.component_instance('pet')
    from PySide6.QtCore import QTimer
    def display_pet():
        if pet is None:
            print('桌宠启动失败：桌宠已停用，未启动。', file=sys.stderr)
            app.exit(1)
            return
        try:
            context = runtime.user_context('pet')
            runtime.client('pet').call('pet', 'show', {}, context=context)
        except Exception as error:
            print(f'桌宠启动失败：{error}', file=sys.stderr)
            app.exit(1)
    QTimer.singleShot(0, display_pet)
    # Native adapters are ready. Respect explicit startup dependencies between restored views.
    excluded = {item[0] for item in definitions}
    pending = {record['manifest']['id'] for record in runtime.export_installations()
               if record['manifest']['id'] not in excluded and record['autostart']
               and record['manifest']['entry'].get('defer') == 'desktop'}
    for identity in tuple(pending):
        try:
            runtime.prepare(identity)
        except Exception as error:
            pending.remove(identity)
            manager.bridge._notice = str(error)
    while pending:
        ready = [identity for identity in pending if not any(
            (dependency.get('target') or runtime.roles.get(dependency.get('role'))) in pending
            for dependency in runtime.status(identity)['description'].get('dependencies', [])
            if dependency.get('kind') == 'startup')]
        if not ready:
            manager.bridge._notice = '组件启动依赖未就绪：' + '、'.join(sorted(pending))
            break
        for identity in ready:
            pending.remove(identity)
            try:
                runtime.start_component(identity)
            except Exception as error:
                manager.bridge._notice = str(error)
    manager.bridge.changed.emit()
    def stop_desktop():
        for identity in ('manager', 'pet', 'canvas', 'window'):
            try:
                runtime.stop_component(identity, persist=False)
            except Exception:
                pass
    app.aboutToQuit.connect(stop_desktop)
    app._polaris_desktop = (host, manager, pet)
    return app.exec()
