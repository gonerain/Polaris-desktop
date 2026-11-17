"""QML imports shared by Polaris-hosted views."""
from pathlib import Path


def configure_qml_engine(engine):
    """Expose the bundled Polaris.Ui module to an existing QML engine."""
    root = str(Path(__file__).resolve().parent / 'qml')
    if root not in engine.importPathList():
        engine.addImportPath(root)
