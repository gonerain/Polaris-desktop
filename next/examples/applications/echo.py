"""Headless composition sample: PYTHONPATH=next python next/examples/applications/echo.py."""
import json
from pathlib import Path

from polaris_platform.application import Application
from polaris_platform.bootstrap import build
from polaris_platform.component import Component


def main():
    root = Path(__file__).resolve().parents[2]
    runtime = build(json.loads((root / 'config.headless.json').read_text()), root)
    def echo():
        component = Component()
        component.operation('echo', applicationBinding='instance')(lambda params, context: {'message': params.get('message', '')})
        return component
    for name, factory in [('demo.user', Component), ('demo.echo', echo)]:
        runtime.install(dict(id=name, name=name, version='1', platformApi=1,
                             entry={'mode': 'inprocess', 'factory': 'unused:create'}), factory)
        runtime.start_component(name)
    try:
        from uuid import uuid4
        app_id = uuid4().hex
        runtime.register_application_principal(app_id)
        client = runtime.application_client(app_id)
        runtime.grant(app_id, 'demo.echo', 'echo')
        status = runtime.status('demo.echo')
        stable_id = status.get('instanceId', status['installation'])
        app = Application('Echo sample', {'echo': {
            'target': stable_id if 'instanceId' in status else 'demo.echo',
            'installationId': status.get('installationId', status['installation']),
            'instanceId': stable_id, 'operation': 'echo',
            'semantic': list(client.bind('demo.echo', 'echo').semantic)}},
            flows={'hello': [{'alias': 'echo', 'input': 'previous'}]},
            pages=[{'id': 'main', 'title': 'Echo', 'action': 'hello'}], application_id=app_id)
        session = app.open(client, runtime.application_context(app_id), runtime.status)
        print(json.dumps(session.run('hello', {'message': 'Hello from an application'})))
        session.stop()
    finally:
        for row in reversed(runtime.snapshot()):
            runtime.stop_component(row['id'], force=True)


if __name__ == '__main__':
    main()
