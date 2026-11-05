"""Application compositions. Execution always uses an ordinary caller's Client."""
from copy import deepcopy
import json
from uuid import UUID, uuid4

from .persistence import read_json, write_json
from .protocol import PlatformError


class Application:
    """Durable composition with no component lifecycle, using only its own explicit grants.

    Bindings pin installation identity and a stable component instance. ``target``
    is the runtime address for that instance; ``semantic`` is a capability key
    returned by Client.bind. Flow steps call aliases sequentially, using either
    literal params or the preceding step's result.
    """
    def __init__(self, title, bindings=None, config=None, flows=None, pages=None,
                 application_id=None):
        if (bindings is not None and not isinstance(bindings, dict)
                or config is not None and not isinstance(config, dict)
                or flows is not None and not isinstance(flows, dict)
                or pages is not None and not isinstance(pages, list)):
            raise PlatformError('invalid_application', 'Bindings, config and flows must be maps; pages must be a list')
        self.id = application_id or uuid4().hex
        try:
            if UUID(self.id).hex != self.id:
                raise ValueError('noncanonical UUID')
        except (ValueError, TypeError, AttributeError) as error:
            raise PlatformError('invalid_application', 'Application identity must be a UUID') from error
        self.title = title
        self.bindings = deepcopy(bindings or {})
        self.config = deepcopy(config or {})
        self.flows = deepcopy(flows or {})
        self.pages = deepcopy(pages or [])
        if not isinstance(self.id, str) or not self.id or not isinstance(title, str):
            raise PlatformError('invalid_application', 'Application identity and title are required')
        for alias, binding in self.bindings.items():
            if not isinstance(binding, dict):
                raise PlatformError('invalid_application', f'Invalid binding: {alias}')
            if 'resource' in binding or 'scope' in binding:
                raise PlatformError('unsupported_resource_scope', 'Resource-scoped application bindings are not supported')
            if any(not binding.get(key) for key in ('target', 'installationId', 'instanceId', 'operation', 'semantic')):
                raise PlatformError('invalid_application', f'Incomplete binding: {alias}')
            semantic = binding['semantic']
            if (not isinstance(alias, str) or not alias
                    or any(not isinstance(binding[key], str) for key in ('target', 'installationId', 'instanceId', 'operation'))
                    or not isinstance(semantic, (list, tuple)) or len(semantic) != 6
                    or semantic[0] != binding['instanceId'] or semantic[1] != 'operation'
                    or semantic[2] != binding['operation'] or semantic[4] not in ('read', 'write')
                    or any(type(semantic[index]) is not int or semantic[index] < 1 for index in (3, 5))):
                raise PlatformError('invalid_application', f'Invalid binding semantics: {alias}')
        for name, steps in self.flows.items():
            if not isinstance(steps, list):
                raise PlatformError('invalid_application', f'Flow must be a list: {name}')
            for step in steps:
                if (not isinstance(step, dict) or set(step) - {'alias', 'input', 'params'}
                        or step.get('alias') not in self.bindings
                        or step.get('input') not in (None, 'previous')
                        or step.get('input') == 'previous' and 'params' in step
                        or not isinstance(step.get('params', {}), dict)):
                    raise PlatformError('invalid_application', f'Invalid flow step: {name}')
        for page in self.pages:
            if (not isinstance(page, dict) or set(page) - {'id', 'title', 'action', 'inputs'}
                    or not isinstance(page.get('id'), str) or not page.get('id')
                    or page.get('action') not in self.flows):
                raise PlatformError('invalid_application', 'Pages require an id and a declared flow action')
            if not isinstance(page.get('title', ''), str) or not isinstance(page.get('inputs', []), list):
                raise PlatformError('invalid_application', 'Page title and inputs have invalid types')
            names = set()
            for field in page.get('inputs', []):
                if (not isinstance(field, dict) or set(field) - {'name', 'label', 'default'}
                        or not isinstance(field.get('name'), str) or not field.get('name')
                        or field['name'] in names or not isinstance(field.get('label'), str)
                        or not field['label'] or not isinstance(field.get('default', ''), str)):
                    raise PlatformError('invalid_application', 'Inputs require unique names, labels and string defaults')
                names.add(field['name'])
        if len({page['id'] for page in self.pages}) != len(self.pages):
            raise PlatformError('invalid_application', 'Page ids must be unique')
        # Reject non-durable objects instead of silently retaining runtime handles.
        json.dumps(self.as_dict(), allow_nan=False)

    def as_dict(self):
        return deepcopy(dict(schemaVersion=1, applicationId=self.id, title=self.title,
                             bindings=self.bindings, config=self.config,
                             flows=self.flows, pages=self.pages))

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or value.get('schemaVersion') != 1:
            raise PlatformError('invalid_application', 'Unsupported application schema')
        return cls(value['title'], value.get('bindings'), value.get('config'),
                   value.get('flows'), value.get('pages'), value['applicationId'])

    def save(self, path):
        write_json(path, self.as_dict())

    @classmethod
    def load(cls, path):
        return cls.from_dict(read_json(path, {}))

    def open(self, client, context, inspect_instance):
        """inspect_instance(target) is a read-only runtime status adapter.

        This callback supplies identity only; it never invokes capabilities or
        creates contexts. A host may pass the public Runtime.status method.
        """
        return ApplicationSession(self, client, context, inspect_instance)


class ApplicationSession:
    def __init__(self, application, client, context, inspect_instance):
        # Sessions retain a snapshot; edits require opening a new session.
        if (client.id != application.id or context.origin != application.id
                or context.origin_installation != application.id):
            raise PlatformError('application_identity_mismatch', 'An application requires its own registered authorization principal')
        self.application = Application.from_dict(application.as_dict())
        self._client, self._context = client, context
        self._inspect = inspect_instance
        self.closed = False

    def stop(self):
        """Close this composition without stopping any shared component."""
        self.closed = True
        self._context = None

    def call(self, alias, params=None):
        if self.closed:
            raise PlatformError('application_closed', self.application.id)
        if params is not None and not isinstance(params, dict):
            raise PlatformError('invalid_application_input', 'Capability parameters must be an object')
        binding = self.application.bindings.get(alias)
        if binding is None:
            raise PlatformError('application_alias_missing', alias)
        try:
            status = self._inspect(binding['target'])
            if (status.get('installationId', status.get('installation')) != binding['installationId']
                    or status.get('instanceId', status.get('installation')) != binding['instanceId']
                    or status.get('state') != 'running'):
                raise PlatformError('application_binding_unavailable', alias)
            metadata = status.get('description', {}).get('operations', {}).get(binding['operation'], {})
            if metadata.get('applicationBinding') != 'instance':
                raise PlatformError('application_binding_unsupported', 'Provider has not declared an instance-stable application binding')
            handle = self._client.bind(binding['target'], binding['operation'])
            if (getattr(handle, 'instanceId', binding['instanceId']) != binding['instanceId']
                    or tuple(handle.semantic) != tuple(binding['semantic'])):
                raise PlatformError('application_binding_unavailable', alias)
        except PlatformError as error:
            if error.code == 'application_binding_unsupported':
                raise
            raise PlatformError('application_binding_unavailable', alias,
                                {'cause': error.code, 'binding': deepcopy(binding)}) from error
        # Authorization errors propagate unchanged; no elevated management path.
        return self._client.invoke(handle, deepcopy(params or {}), context=self._context)

    def run(self, flow, params=None):
        if self.closed:
            raise PlatformError('application_closed', self.application.id)
        if flow not in self.application.flows:
            raise PlatformError('application_flow_missing', flow)
        result = deepcopy(params or {})
        for step in self.application.flows[flow]:
            result = self.call(step['alias'], result if step.get('input') == 'previous' else step.get('params', {}))
        return result


class ApplicationStore:
    """Application-owned durable definitions; no component profile or data copy."""
    def __init__(self, directory):
        from pathlib import Path
        self.directory = Path(directory)

    def _path(self, application_id):
        try:
            if UUID(application_id).hex != application_id:
                raise ValueError('noncanonical UUID')
        except (ValueError, TypeError, AttributeError) as error:
            raise PlatformError('invalid_application', 'Application identity must be a UUID') from error
        return self.directory / (application_id + '.json')

    def save(self, application):
        application.save(self._path(application.id))

    def load(self, application_id):
        path = self._path(application_id)
        if not path.exists():
            raise PlatformError('application_missing', application_id)
        application = Application.load(path)
        if application.id != application_id:
            raise PlatformError('invalid_application', 'Application file identity does not match its name')
        return application

    def list(self):
        if not self.directory.exists():
            return []
        return [self.load(path.stem).as_dict() for path in sorted(self.directory.glob('*.json'))]

    def delete(self, application_id):
        self._path(application_id).unlink(missing_ok=True)
