"""The platform exposes its bundled QML module to existing host engines."""
import os
import subprocess
import sys
import unittest
from pathlib import Path


class QmlUiImportTest(unittest.TestCase):
    def test_external_qml_import_in_both_host_engines(self):
        code = r'''
import tempfile
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtCore import QUrl, QObject, Signal
from PySide6.QtGui import QGuiApplication
from components.window import WindowHost
from polaris_platform.ui import configure_qml_engine
from polaris_platform.desktop.application_view import ApplicationView
app=QGuiApplication([])
with tempfile.TemporaryDirectory() as d:
    qml=Path(d)/'External.qml'
    qml.write_text('import QtQuick 2.15\nimport Polaris.Ui 1.0 as Ui\nItem { Ui.Theme { id: colors } Ui.Button { objectName: "uiProbeButton"; theme: colors } }\n')
    host_window=WindowHost()
    host_window.start(None)
    handle=host_window.create_view(str(qml), "external")
    view=host_window._views[handle]
    configure_qml_engine(view.engine())
    assert view.rootObject(), [e.toString() for e in view.errors()]
    assert view.rootObject().findChild(QObject, 'uiProbeButton').property('theme') is not None
    class Host(QObject):
        changed=Signal()
        _backends={}
        def application_data_directory(self, identity): return Path(d)/identity
    application=SimpleNamespace(id='external')
    child=ApplicationView(Host(),application,qml,view.rootObject())
    assert child.root is not None
    child.close()
    host_window.stop()
'''
        env=dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software')
        result=subprocess.run([sys.executable,'-c',code],cwd='/tmp',env=env,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
