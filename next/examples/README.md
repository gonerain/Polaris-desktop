# Independent example software

`notes` owns its notes. `labeler` reads a note through `ctx.call` and stores its own tags. Both use only `polaris_platform.sdk`; adding another business field requires no platform changes.

Each directory has a process manifest. `{python}` selects the host's current interpreter. The host runs the command from the manifest's directory. Install the `next` package in that interpreter, or set `PYTHONPATH` to the absolute `next` directory while developing. stdout is reserved for JSON-lines protocol; SDK redirects ordinary prints to stderr.

The same factories also work in process:

```python
from examples.notes.main import create as create_notes
from examples.labeler.main import create as create_labeler
```

Choose either the process adapter or these factories in the assembly configuration. The labeler's handler stays unchanged. Through the user management facade, grant the request origin `notes.create`, `notes.get` and `labeler.label` as needed. A request allowed to call `labeler.label` alone receives a denial when it attempts `notes.get`; the labeler's own standing grants cannot supply that missing request permission.

Handlers use keyword arguments and may accept `ctx` for nested calls. Business validation belongs in handlers. Read/write descriptions do not authorize access. `component.port.advertise()` republishes current descriptions after a component changes its own declarations; newly published capabilities need explicit user grants. No process adapter grants permissions.

A timed-out call has an unknown business result. Its token expires immediately and the adapter rejects further business calls on that instance until it is stopped and restarted. It does not replay the operation. A stop request that leaves the child alive reports `stopping`; management may explicitly force-stop it.

`counter/` is a trusted local Qt-native view example. Its own QML and counter model are mounted by the canvas through the public create/release view contract; see [counter](counter/README.md).
