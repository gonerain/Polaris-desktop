"""Optional Qt Quick desktop components and trusted local management UI."""
from importlib import import_module
from components import DESKTOP, ROOT, manifest as bundled_manifest

# Preserve public imports used by existing third-party plugins and saved manifests.
def __getattr__(name):
    if name in ('Manager', 'create_manager'):
        return getattr(import_module('components.manager'), name)
    if name == 'create_sources':
        return import_module('components.sources').create_sources
    if name == 'DesktopUserAccess':
        return import_module('.user_access', __name__).DesktopUserAccess
    if name in ('GuiDispatcher', 'WindowHost', 'Canvas', 'Pet', 'create_window', 'create_canvas', 'create_pet'):
        return getattr(import_module('.components', __name__), name)
    raise AttributeError(name)


def run(runtime):
    """Launch the optional desktop against an existing platform runtime."""
    import sys
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    from ..metadata import APP_NAME, VERSION
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    app.setApplicationDisplayName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    from PySide6.QtGui import QIcon
    app.setWindowIcon(QIcon(str(ROOT / 'pet/skins/dshpet/poster.webp')))
    from ..bootstrap import load_factory
    installed = {item['id']: item for item in runtime.snapshot()}
    saved = {item['manifest']['id']: item for item in runtime.export_installations()}
    removed = runtime.removed_installations()
    startup_errors = []
    for identity in DESKTOP:
        if identity in removed:
            continue
        try:
            if identity not in installed:
                manifest = bundled_manifest(identity)
                runtime.install(manifest, load_factory(manifest, ROOT / identity, runtime, trusted_bindings=True),
                                trusted_bindings=True)
            if identity not in installed or identity in ('window', 'manager') or saved[identity]['autostart']:
                runtime.start_component(identity)
        except Exception as error:
            message = f'组件 {identity} 启动失败：{error}'
            print(message, file=sys.stderr)
            startup_errors.append(message)
    running = {row['id'] for row in runtime.snapshot() if row['state'] == 'running'}
    host = runtime.component_instance('window') if 'window' in running else None
    from .management_control import ManagementControlPort
    management = ManagementControlPort(runtime)
    # These are the precise, installed capabilities of the default local interaction.
    # Existing installations retain every user revocation and never gain new items here.
    pet_is_new = 'pet' not in installed and 'pet' not in removed
    defaults = [('pet', 'show', 'operation'), ('pet', 'hide', 'operation'),
                ('canvas', 'show', 'operation'), ('canvas', 'status', 'operation'), ('canvas', 'dismissed', 'event'),
                ('manager', 'show', 'operation')]
    defaults += [('window', name, 'operation') for name in ('status', 'create', 'show', 'hide', 'update', 'move')]
    if pet_is_new and 'pet' in running:
        for target, name, kind in defaults:
            if target not in running:
                continue
            runtime.grant('pet', target, name, kind=kind)
    pet = runtime.component_instance('pet') if 'pet' in running else None
    if startup_errors:
        management.report_notice('\n'.join(startup_errors))
    from PySide6.QtCore import QTimer
    # Application distribution updates belong to the host, outside component permissions.
    if sys.platform == 'linux' and getattr(sys, 'frozen', False):
        from .updates import UpdateController
        app._polaris_updates = UpdateController(app)
        QTimer.singleShot(5000, app._polaris_updates.check_on_startup)
    def show_management():
        try:
            management.show()
        except Exception as error:
            print(f'组件管理无法显示：{error}', file=sys.stderr)

    def display_pet():
        if 'pet' in removed or 'window' in removed:
            # Keep a trusted management entry available after removing or disabling
            # the usual desktop entry point, without reinstalling that component.
            show_management()
            return
        if pet is None:
            print('桌宠启动失败：桌宠已停用，未启动。', file=sys.stderr)
            show_management()
            return
        try:
            context = runtime.user_context('pet')
            runtime.client('pet').call('pet', 'show', {}, context=context)
        except Exception as error:
            print(f'桌宠启动失败：{error}', file=sys.stderr)
            management.report_notice('\n'.join([*startup_errors, f'桌宠启动失败：{error}']))
            show_management()
    QTimer.singleShot(0, display_pet)
    # Native adapters are ready. Respect explicit startup dependencies between restored views.
    excluded = set(DESKTOP)
    pending = {record['manifest']['id'] for record in runtime.export_installations()
               if record['manifest']['id'] not in excluded and record['autostart']
               and record['manifest']['entry'].get('defer') == 'desktop'}
    for identity in tuple(pending):
        try:
            runtime.prepare(identity)
        except Exception as error:
            pending.remove(identity)
            management.report_notice(str(error))
    while pending:
        ready = [identity for identity in pending if not any(
            (dependency.get('target') or runtime.roles.get(dependency.get('role'))) in pending
            for dependency in runtime.status(identity)['description'].get('dependencies', [])
            if dependency.get('kind') == 'startup')]
        if not ready:
            management.report_notice('组件启动依赖未就绪：' + '、'.join(sorted(pending)))
            break
        for identity in ready:
            pending.remove(identity)
            try:
                runtime.start_component(identity)
            except Exception as error:
                management.report_notice(str(error))
    management.refresh()
    def stop_desktop():
        for identity in reversed(DESKTOP):
            try:
                runtime.stop_component(identity, persist=False)
            except Exception:
                pass
    app.aboutToQuit.connect(stop_desktop)
    app._polaris_desktop = (host, pet)
    return app.exec()
