"""A stdio provider and consumer used to exercise registration inside live requests."""
from polaris_platform.sdk import Component

component = Component()
received = []


@component.operation('configure', access='write')
def configure(enabled):
    if not enabled:
        component.withdraw_event('news')
        component.withdraw_operation('fetch')
        return
    component.event('news', provides='example.changed@1')

    @component.operation('fetch', provides='notes.read@1')
    def fetch(id):
        return {'id': id, 'title': 'Remote notebook', 'body': 'published'}


@component.operation('listen', requires={'news': {'contract': 'example.incoming@1', 'kind': 'event'},
                                         'name': 'example.name@1'})
def listen(ctx):
    return ctx.subscribe_required('news', lambda value, ctx: received.append([value, ctx.call_required('name')]))


@component.operation('received')
def messages():
    return list(received)


component.run()
