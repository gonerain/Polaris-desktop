"""Run through the frozen launcher; require a visible pet with its bundled skin.

Invoked by build_deb.py with an isolated data directory. Only preset network
installation is disabled so desktop packaging checks work without GitHub access.
"""
import json
import sys
from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication, QImage
from polaris_platform import bootstrap
from polaris_platform.__main__ import main

app = QGuiApplication([])
original_build = bootstrap.build
runtimes = []
verified = False


def capture_runtime(*args, **kwargs):
    runtime = original_build(*args, **kwargs)
    runtime.manager_config['defaultSources'] = []
    runtimes.append(runtime)
    return runtime


bootstrap.build = capture_runtime


def verify():
    global verified
    if not runtimes:
        return
    runtime = runtimes[0]
    pet = runtime.component_instance('pet')
    host = runtime.component_instance('window')
    if not pet or not pet.handle:
        return
    view = host._views[pet.handle]
    root = view.rootObject()
    if not view.isVisible() or not root or not root.property('skinReady'):
        return
    if root.property('skinError'):
        raise RuntimeError(root.property('skinError'))
    # QML can report skinReady before the first animated image is painted.
    image = view.grabWindow().convertToFormat(QImage.Format_RGBA8888)
    if image.isNull() or not any(image.constBits().tobytes()[3::4]):
        return
    # Let the initial asynchronous management refresh finish before requesting
    # exit, rather than interrupting a GUI callback at the first rendered frame.
    manager = runtime.component_instance('manager')
    if manager.bridge.busy or (manager.bridge._worker and manager.bridge._worker.is_alive()):
        return
    from components.mcp.stdio import forward
    mcp = runtime.component_instance('mcp')
    if runtime.status('mcp')['state'] != 'running':
        raise RuntimeError('MCP component did not start')
    reply = forward({'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}, mcp.directory / 'endpoint.json')
    if reply.get('result') != {}:
        raise RuntimeError('MCP endpoint did not respond')
    verified = True
    print(json.dumps({'petVisible': True, 'skinReady': True, 'mcpReady': True, 'installation': runtime.status('pet')['installation']}), flush=True)
    app.quit()


timer = QTimer()
timer.timeout.connect(verify)
timer.start(25)
QTimer.singleShot(8000, lambda: app.exit(2))
result = main(['--gui', '--state-dir', sys.argv[1]])
raise SystemExit(result if result else (0 if verified else 2))
