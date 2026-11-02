"""Cooperative lifecycle manager and authenticated instance-bound ports."""
import contextvars
from copy import deepcopy
from polaris_platform.contracts import DirectoryGraph
import hashlib
import hmac
import secrets
import json
from pathlib import Path
from threading import RLock
from uuid import uuid4
from dataclasses import replace
from polaris_platform.component import Component
from polaris_platform.protocol import Context, Handle, PlatformError, capability, validate_description, _dispatched, handler_signature

_active = contextvars.ContextVar("polaris_request", default=None)
_native_view = contextvars.ContextVar("polaris_native_view", default=None)


_invocation_bindings = contextvars.ContextVar('polaris_invocation_bindings', default=None)


class RequiredBindings:
    """Endpoints pinned to the selected instances for one operation or event subscription."""
    def __init__(self, client, bindings):
        self.client = client
        self.bindings = bindings

    def handle(self, alias, kind='operation'):
        binding = self.bindings.get(alias)
        if not binding or binding['kind'] != kind:
            raise PlatformError('missing_requirement', alias)
        if 'issue' in binding:
            raise PlatformError('dependency_unavailable', f"{alias}: {binding['issue']}", binding['issue'])
        endpoint = binding['endpoint']
        return Handle(endpoint['target'], endpoint['instance'], endpoint['name'], tuple(endpoint['key']),
                      binding['contract'], endpoint['generation'])

    def call(self, alias, params, context):
        return self.client.invoke(self.handle(alias), params, context)

    def subscribe(self, alias, callback, context):
        handle = self.handle(alias, 'event')
        return self.client.subscribe(handle.target, handle.operation, callback, context=context, expected=handle)


class Client:
    def __init__(self, runtime, component_id, instance):
        self.__runtime, self.id, self.instance = runtime, component_id, instance

    def _context(self, context=None):
        self.__runtime.validate_client(self)
        active = _active.get()
        if context is None:
            if active is not None:
                raise PlatformError("context_required", "Nested work must retain its request context")
            raise PlatformError("context_required", "Use an explicitly granted background or user context")
        self.__runtime.validate_context(context)
        if active is not None and (context.origin != active.origin or context.source != active.source or context.request_id != active.request_id or not context.scope <= active.scope):
            raise PlatformError("scope_escalation", "A nested request cannot replace its authority")
        return self.__runtime.derive_context(context, caller=self.id)

    def bind(self, target, operation):
        self.__runtime.validate_client(self)
        return self.__runtime.collaboration.bind(target, operation)

    def call(self, target, operation, params=None, context=None):
        return self.invoke(self.bind(target, operation), params, context)

    def invoke(self, handle, params=None, context=None):
        return self.__runtime.collaboration.invoke(handle, params or {}, self._context(context))

    def requirements(self, name, kind='operation'):
        self.__runtime.validate_client(self)
        invocation = _invocation_bindings.get()
        if invocation and invocation[:4] == (self.__runtime, self.instance, kind, name):
            bindings = invocation[4]
        else:
            bindings = self.__runtime.resolved_requirements(self.id, kind, name, self.instance)
        return RequiredBindings(self, bindings)

    def subscribe(self, target, event, callback, context=None, expected=None):
        context = self._context(context)
        if expected is None:
            return self.__runtime.collaboration.subscribe(target, event, callback, context)
        return self.__runtime.collaboration.subscribe(target, event, callback, context, expected=expected)

    def unsubscribe(self, token):
        self.__runtime.validate_client(self)
        return self.__runtime.collaboration.unsubscribe(token, self.id)

    def publish(self, event, payload, context=None):
        return self.__runtime.collaboration.publish(self.id, event, payload, self._context(context))

    def advertise(self):
        self.__runtime.validate_client(self)
        self.__runtime.refresh(self.id, self.instance)

    def local_view_input(self, parent):
        self.__runtime.validate_client(self)
        native = _native_view.get()
        if native is None or native[:3] != (self.__runtime, self.id, self.instance) or native[3] is not parent:
            raise PlatformError('permission_denied', 'Local input is only available while creating this native view')
        from polaris_platform.desktop.native_input import NativeViewInput
        return NativeViewInput(self.__runtime, self, parent)

    def require_permissions(self, operations, context):
        context = self._context(context)
        for target, operation in operations:
            handle = self.bind(target, operation)
            self.__runtime.authorization.check(context, handle.semantic)

    def background_context(self):
        raise PlatformError("explicit_background_required", "Trusted user management must issue a background context for an explicit task")

    def remember_task(self, name, operations, context):
        context = self._context(context)
        self.__runtime.remember_task(self, name, operations, context)

    def forget_task(self, name, context):
        self._context(context)
        self.__runtime.forget_task(self, name)

    def resume_task(self, name):
        self.__runtime.validate_client(self)
        if _active.get() is not None:
            raise PlatformError('scope_escalation', 'Task restoration cannot replace an active request')
        return self.__runtime.resume_task(self, name)


class Runtime(Component):
    def __init__(self):
        super().__init__()
        self._lock = RLock()
        self._records = {}
        self._seal = secrets.token_bytes(32)
        self.collaboration = self.authorization = None
        self.roles = {}
        self._authorization_records = []
        self._storage = None
        self._removed_installations = set()
        self._state_dir = None
        self._tasks, self._task_storage = {}, None
        self._selections = {}
        self._selection_storage = None
        self._contract_history = {}
        self._contract_storage = None
        self._graph = DirectoryGraph({}, {})
        self.operation("list")(lambda p, c: self.snapshot())
        self.operation("start", access="write")(lambda p, c: self.start_component(p["id"]))
        self.operation("stop", access="write")(lambda p, c: self.stop_component(p["id"]))
        self.operation("dependencies")(lambda p, c: self.dependency_status(p["id"]))

    def connect(self, collaboration, authorization):
        self.collaboration, self.authorization = collaboration, authorization
        collaboration.runtime = self
        for identity, record in self._records.items():
            authorization.bind_identity(identity, record["installation"])

    def install(self, manifest, factory, installation_id=None, directory=None, autostart=False, trusted_bindings=False):
        self.validate_manifest(manifest)
        component_id = manifest["id"]
        with self._lock:
            if component_id in self._records:
                raise PlatformError("already_installed", component_id)
            self._records[component_id] = dict(manifest=dict(manifest), factory=factory,
                installation=installation_id or uuid4().hex, instance=None, state="installed", component=None, error=None, directory=str(Path(directory).resolve()) if directory else None, autostart=bool(autostart), trustedBindings=bool(trusted_bindings))
        if self.authorization is not None:
            self.authorization.bind_identity(component_id, self._records[component_id]["installation"])
        self._removed_installations.discard(component_id)
        self._persist()
        return component_id

    @staticmethod
    def validate_manifest(manifest):
        if not isinstance(manifest, dict):
            raise PlatformError("invalid_manifest", "Manifest must be an object")
        for key in ("id", "name", "version", "platformApi", "entry"):
            if key not in manifest:
                raise PlatformError("invalid_manifest", f"Missing {key}")
        if not isinstance(manifest["id"], str) or not manifest["id"] or not isinstance(manifest["entry"], dict):
            raise PlatformError("invalid_manifest", "ID must be a nonempty string and entry an object")
        if manifest["platformApi"] != 1 or manifest["entry"].get("mode") not in ("process", "inprocess"):
            raise PlatformError("invalid_manifest", "Unsupported platform API or entry mode")
        entry = manifest["entry"]
        if entry["mode"] == "process":
            command = entry.get("command")
            if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
                raise PlatformError("invalid_manifest", "Process entry requires a nonempty command array")
        if not isinstance(entry.get("kwargs", {}), dict):
            raise PlatformError("invalid_manifest", "Entry kwargs must be an object")

    def export_installations(self):
        """Public manager migration record; component-owned data is not included."""
        with self._lock:
            return [{"manifest": dict(r["manifest"]), "installationId": r["installation"],
                     "directory": r["directory"], "autostart": r["autostart"], "trustedBindings": r["trustedBindings"]}
                    for r in self._records.values()]

    def import_installations(self, records, factory_resolver):
        if _active.get() is not None:
            raise PlatformError("permission_denied", "Import requires trusted user management")
        return [self.install(item["manifest"], factory_resolver(item["manifest"]), item["installationId"], item.get("directory"), item.get("autostart", False), item.get("trustedBindings", False))
                for item in records]

    def replace_component(self, component_id, manifest, factory):
        """Trusted update, retaining installation identity through a public control API."""
        if _active.get() is not None:
            raise PlatformError("permission_denied", "Replacement requires trusted user management")
        if manifest.get("id") != component_id or manifest.get("platformApi") != 1:
            raise PlatformError("invalid_manifest", "Replacement must preserve component ID and API")
        if component_id == self.roles.get("runtime"):
            raise PlatformError("restart_required", "Changing the management implementation requires a new bootstrap")
        self.stop_component(component_id)
        record = self._record(component_id)
        record.update(manifest=dict(manifest), factory=factory, component=None)
        return self.start_component(component_id)

    def management_options(self, component_id):
        record = self._record(component_id)
        injected = any(isinstance(value, dict) and (value.get("runtime") is True or "component" in value)
                       for value in record["manifest"]["entry"].get("kwargs", {}).values())
        protected = component_id in self.roles.values()
        management_self = getattr(self, "management_component_id", None) == component_id
        protected = protected or management_self
        return {"uninstall": not protected, "replace": not protected and not injected,
                "reason": "Changing foundation or management control components requires a new bootstrap" if protected else
                ("Directory replacement of trusted control bindings requires a new bootstrap" if injected else None)}

    def _check_management(self, component_id, action="replace"):
        if _active.get() is not None:
            raise PlatformError("permission_denied", "Installation changes require trusted user management")
        options = self.management_options(component_id)
        if not options[action]:
            raise PlatformError("restart_required", options["reason"])
        if self._record(component_id)["state"] == "starting":
            raise PlatformError("busy", component_id)

    def uninstall_component(self, component_id):
        self._check_management(component_id, "uninstall")
        self.stop_component(component_id, persist=False)
        record = self._record(component_id)
        from polaris_platform.bootstrap import invalidate_plugin_modules
        try:
            invalidate_plugin_modules(record["manifest"], record["directory"], installations=self.export_installations())
        except PlatformError:
            pass  # Shared package entries remain loaded until host restart.
        with self._lock:
            del self._records[component_id]
            self._removed_installations.add(component_id)
            self._persist()
        return {"id": component_id, "state": "uninstalled"}

    def install_directory(self, path, replace=False):
        if _active.get() is not None:
            raise PlatformError("permission_denied", "Installation changes require trusted user management")
        from polaris_platform.bootstrap import load_factory, invalidate_plugin_modules
        directory = Path(path).resolve()
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        self.validate_manifest(manifest)
        factory = load_factory(manifest, directory, self)
        component_id = manifest["id"]
        if component_id not in self._records:
            # A fresh shared entry may legitimately reuse an already loaded
            # package. Do not invalidate another installation's code.
            reference = manifest["entry"].get("factory") or manifest["entry"].get("callable") or ""
            root = reference.split(":")[0].split(".")[0]
            shared = any((item["manifest"]["entry"].get("factory") or item["manifest"]["entry"].get("callable") or "").split(":")[0].split(".")[0] == root
                         for item in self.export_installations())
            if not shared:
                invalidate_plugin_modules(manifest, directory, installations=self.export_installations())
            return self.install(manifest, factory, directory=directory)
        if not replace:
            raise PlatformError("already_installed", component_id)
        self._check_management(component_id)
        record = self._record(component_id)
        # Validate reload eligibility before withdrawing the old instance.
        invalidate_plugin_modules(record["manifest"], record["directory"], check_only=True, installations=self.export_installations())
        invalidate_plugin_modules(manifest, directory, check_only=True, installations=self.export_installations())
        running, autostart = record["state"] == "running", record["autostart"]
        self.stop_component(component_id, persist=False)
        invalidate_plugin_modules(record["manifest"], record["directory"], installations=self.export_installations())
        invalidate_plugin_modules(manifest, directory, installations=self.export_installations())
        record.update(manifest=dict(manifest), factory=factory, directory=str(directory),
                      component=None, error=None, autostart=autostart)
        self._persist()
        if running:
            self.start_component(component_id)
        return component_id

    def _record(self, component_id):
        try:
            return self._records[component_id]
        except KeyError:
            raise PlatformError("not_installed", component_id) from None

    def removed_installations(self):
        return frozenset(self._removed_installations)

    def load_installations(self, path):
        from polaris_platform.persistence import read_json
        self._selection_storage = Path(path).with_name('capability-bindings.json')
        self._selections = read_json(self._selection_storage, {})
        self._contract_storage = Path(path).with_name('capability-contracts.json')
        self._contract_history = read_json(self._contract_storage, {})
        self._task_storage = Path(path).with_name('tasks.json')
        self._tasks = read_json(self._task_storage, {})
        self._removed_installations = set(read_json(Path(path).with_name("removed-installations.json"), []))
        return [item for item in read_json(path, []) if item["manifest"]["id"] not in self._removed_installations]

    def configure_storage(self, state_dir):
        self._state_dir = Path(state_dir).resolve()
        self._storage = self._state_dir / "installations.json"
        self._persist()
        self.authorization.configure_storage(self._state_dir / "authorization.json")
        self._task_storage = self._state_dir / 'tasks.json'
        self._persist_tasks()

    def _task_key(self, client, name):
        self.validate_client(client)
        if not isinstance(name, str) or not name or len(name) > 64:
            raise PlatformError('invalid_params', 'Invalid task name')
        return self._record(client.id)['installation'] + ':' + name

    def remember_task(self, client, name, operations, context):
        """Persist a user-authorized delegation, never a serialized Context."""
        self.validate_context(context)
        if context.source != 'user':
            raise PlatformError('permission_denied', 'Task setup requires user authority')
        key = self._task_key(client, name)
        selected = {(self._record(target)['installation'], operation) for target, operation in operations}
        scope = [list(cap) for cap in context.scope
                 if cap[1] == 'operation' and (cap[0], cap[2]) in selected]
        with self._lock:
            previous = self._tasks.get(key)
            self._tasks[key] = dict(origin=context.origin, originInstallation=context.origin_installation, scope=scope)
            try:
                self._persist_tasks()
            except Exception:
                if previous is None:
                    self._tasks.pop(key, None)
                else:
                    self._tasks[key] = previous
                raise

    def forget_task(self, client, name):
        with self._lock:
            key = self._task_key(client, name)
            previous = self._tasks.pop(key, None)
            try:
                self._persist_tasks()
            except Exception:
                if previous is not None:
                    self._tasks[key] = previous
                raise

    def resume_task(self, client, name):
        from polaris_platform.protocol import Context
        with self._lock:
            task = self._tasks.get(self._task_key(client, name))
            if task is None:
                return None
            origin = self._record(task['origin'])
            if origin['installation'] != task['originInstallation']:
                raise PlatformError('stale_instance', 'Task authorization owner was replaced')
            # Every operation still checks the current authorization record.
            return self._stamp(Context(task['origin'], client.id, 'user',
                frozenset(tuple(cap) for cap in task['scope']), origin_installation=task['originInstallation']))

    def _persist_tasks(self):
        if self._task_storage is not None:
            from polaris_platform.persistence import write_json
            write_json(self._task_storage, self._tasks)

    def _persist(self):
        if self._storage is not None:
            from polaris_platform.persistence import write_json
            with self._lock:
                write_json(self._storage.with_name("removed-installations.json"), sorted(self._removed_installations))
                write_json(self._storage, self.export_installations())

    def component_data_directory(self, component_id):
        """Trusted assembly location; each component owns its data beneath it."""
        record = self._record(component_id)
        return self._state_dir / 'components' / record['installation'] if self._state_dir is not None else None

    def component_instance(self, component_id):
        return self._record(component_id)["component"]

    def prepare(self, component_id):
        record = self._record(component_id)
        if record["component"] is None:
            record["component"] = record["factory"]()
        return record["component"]

    def start_component(self, component_id):
        with self._lock:
            record = self._record(component_id)
            if record["state"] == "running":
                return self.status(component_id)
            if record["state"] in ("starting", "stopping"):
                raise PlatformError("busy", component_id)
            record.update(state="starting", instance=uuid4().hex, error=None, generations={}, published={})
        try:
            component = self.prepare(component_id)
            if component_id == self.roles.get("collaboration"):
                self.connect(component, self.authorization)
            elif component_id == self.roles.get("authorization"):
                component.import_records(self._authorization_records)
                if self._state_dir is not None:
                    component.configure_storage(self._state_dir / "authorization.json")
                self.connect(self.collaboration, component)
            if hasattr(component, "set_failure_callback"):
                instance = record["instance"]
                component.set_failure_callback(lambda error=None: self.mark_failed(component_id, error, instance))
            description = validate_description(component.describe())
            for dependency in description.get("dependencies", []):
                if dependency.get("kind") == "startup" and not self._dependency_available(dependency):
                    raise PlatformError("dependency_unavailable", "Startup dependency missing", dependency)
            component.start(Client(self, component_id, record["instance"]))
            record["state"] = "running"
            record["autostart"] = True
            self._persist()
            self.refresh(component_id, record['instance'])
            return self.status(component_id)
        except Exception as error:
            component = record.get("component")
            if component is not None:
                try:
                    component.stop()
                except Exception:
                    if hasattr(component, "force_stop"):
                        try:
                            component.force_stop()
                        except Exception:
                            pass
            record.update(state="failed", error=str(error), component=None)
            self.collaboration.withdraw(component_id)
            self.refresh_all()
            raise

    def stop_component(self, component_id, force=False, persist=True):
        record = self._record(component_id)
        if record["state"] in ("installed", "stopped"):
            return self.status(component_id)
        with self._lock:
            if persist:
                record["autostart"] = False
                self._persist()
            record["state"] = "stopping"
            self.collaboration.withdraw(component_id)
        self.refresh_all()
        try:
            component = record["component"]
            if component is not None and component_id == self.roles.get("authorization"):
                self._authorization_records = component.export_records()
            if component is not None:
                if force and hasattr(component, "force_stop"):
                    component.force_stop()
                else:
                    component.stop()
            record["state"] = "stopped"
            record["component"] = None
        except PlatformError as error:
            record["error"] = error.as_dict()
            if error.code != "stopping":
                record["state"] = "failed"
            raise
        except Exception as error:
            record.update(state="failed", error=str(error))
            raise
        finally:
            self.refresh_all()
        return self.status(component_id)

    def mark_failed(self, component_id, error=None, instance=None):
        record = self._record(component_id)
        if instance is not None and record["instance"] != instance:
            return
        record.update(state="failed", error=str(error) if error else "Process exited")
        self.collaboration.withdraw(component_id)
        self.refresh_all()

    def client(self, component_id):
        record = self._record(component_id)
        return Client(self, component_id, record["instance"])

    def validate_client(self, client):
        record = self._record(client.id)
        if record["instance"] != client.instance or record["state"] not in ("running", "starting"):
            raise PlatformError("stale_instance", client.id)

    def _signature(self, context):
        value = [context.origin, context.origin_installation, context.caller, context.source,
                 context.request_id, sorted(context.scope)]
        return hmac.new(self._seal, json.dumps(value, sort_keys=True).encode(), hashlib.sha256).digest()

    def _stamp(self, context):
        return replace(context, _seal=self._signature(context))

    def validate_context(self, context):
        if not isinstance(context, Context) or not isinstance(context._seal, bytes):
            raise PlatformError("invalid_context", "Context must originate at trusted bootstrap")
        try:
            valid = hmac.compare_digest(context._seal, self._signature(context))
        except (TypeError, ValueError):
            valid = False
        if not valid:
            raise PlatformError("invalid_context", "Context identity or scope was altered")

    def derive_context(self, context, *, caller=None, scope=None):
        self.validate_context(context)
        if scope is not None and not frozenset(scope) <= context.scope:
            raise PlatformError("scope_escalation", "Context derivation may only narrow scope")
        return self._stamp(replace(context, caller=caller or context.caller,
                                   scope=context.scope if scope is None else frozenset(scope)))

    def user_context(self, requester, targets=None):
        if _active.get() is not None:
            raise PlatformError("scope_escalation", "User authority is unavailable inside request handlers")
        self._record(requester)
        scope = self.authorization.scope(requester)
        if targets is not None:
            scope = frozenset(k for k in scope if k[0] in targets)
        return self._stamp(Context(requester, requester, "user", scope, origin_installation=self._record(requester)["installation"]))

    def background_context(self, requester):
        if _active.get() is not None:
            raise PlatformError("scope_escalation", "Background authority is unavailable inside request handlers")
        return self._stamp(Context(requester, requester, "background", self.authorization.scope(requester, True), origin_installation=self._record(requester)["installation"]))

    def grant(self, requester, target, name, kind="operation", background=False, expected_key=None):
        if _active.get() is not None:
            raise PlatformError("permission_denied", "Only trusted user management can grant authority")
        self._record(requester)
        record = self.collaboration.describe_target(target)
        metadata = record["description"].get("operations" if kind == "operation" else "events", {}).get(name)
        if metadata is None:
            raise PlatformError("missing_capability", name)
        key = capability(record['installation'], kind, name, metadata)
        if expected_key is not None and key != tuple(expected_key):
            raise PlatformError('stale_selection', name)
        self.authorization.grant(requester, key, background)

    def revoke(self, requester, target, name, kind="operation", background=False):
        if _active.get() is not None:
            raise PlatformError("permission_denied", "Only trusted user management can revoke authority")
        record = self._record(target)
        for key in self.authorization.scope(requester, background):
            if key[:3] == (record["installation"], kind, name):
                self.authorization.revoke(requester, key, background)

    def dispatch(self, handle, params, context):
        self.validate_context(context)
        record = self._record(handle.target)
        if record["state"] != "running" or record["instance"] != handle.instance:
            raise PlatformError("stale_handle", handle.target)
        description = self.collaboration.describe_target(handle.target)['description']
        metadata = description['operations'].get(handle.operation)
        if (metadata is None or not metadata.get('available', True) or handle.generation != metadata.get('generation', 0)
                or handle.contract != metadata.get('provides')
                or capability(record['installation'], 'operation', handle.operation, metadata) != handle.semantic):
            raise PlatformError('stale_handle', handle.operation)
        component = record['component']
        bindings = self.resolved_requirements(handle.target, 'operation', handle.operation, handle.instance) if metadata.get('requires') else {}
        native_create = context.source == 'user' and metadata.get('profile') == 'qt-native' and 'parent' in params and any(
            view.get('adapter') == 'qt-quick-item' and view.get('id') == params.get('view')
            and view.get('create', 'create_view') == handle.operation
            for view in description.get('views', []))
        token = _active.set(context)
        binding_token = _invocation_bindings.set((self, handle.instance, 'operation', handle.operation, bindings))
        signature_token = _dispatched.set(handler_signature(metadata))
        native_token = _native_view.set((self, handle.target, handle.instance, params['parent'])
            if native_create else None)
        try:
            result = component.call(handle.operation, params, context)
            return result
        except PlatformError:
            raise
        except (TypeError, ValueError) as error:
            raise PlatformError("invalid_data", str(error)) from error
        except Exception as error:
            raise PlatformError("component_error", str(error)) from error
        finally:
            _dispatched.reset(signature_token)
            _invocation_bindings.reset(binding_token)
            _native_view.reset(native_token)
            _active.reset(token)

    def derive_event_context(self, subscription, publisher):
        self.validate_context(publisher)
        return self.derive_context(publisher, caller=subscription.caller, scope=publisher.scope & subscription.scope & self.authorization.scope(subscription.origin, subscription.source == "background"))

    def deliver(self, caller, callback, payload, context):
        token = _active.set(context)
        try:
            return callback(payload, context)
        finally:
            _active.reset(token)

    def _dependency_available(self, dependency):
        target = dependency.get("target") or self.roles.get(dependency.get("role"))
        record = self._records.get(target)
        if not record or record["state"] != "running":
            return False
        desc = record.get('published', {})
        interface = dependency.get("interface")
        if interface:
            return any(m.get("interface") == interface and m.get("major", 1) == dependency.get("major", 1)
                       for m in desc.get("operations", {}).values())
        return True

    def dependency_status(self, component_id):
        record = self._record(component_id)
        description = record["component"].describe() if record["component"] else {}
        return [dict(d, available=self._dependency_available(d)) for d in description.get("dependencies", [])]

    def _contract_updates(self, installation, description):
        # Preserve existing directed grants when first adopting a public contract.
        # Once named, a different contract needs a different authorization key,
        # even if the old implementation was withdrawn or the host restarted.
        updates = {}
        for kind, group in (('operation', 'operations'), ('event', 'events')):
            for name, meta in description.get(group, {}).items():
                if 'provides' not in meta:
                    continue
                key = json.dumps(capability(installation, kind, name, meta), separators=(',', ':'))
                previous = self._contract_history.get(key)
                if previous is None:
                    updates[key] = meta['provides']
                elif previous != meta['provides']:
                    raise PlatformError('invalid_description',
                                        f'{name}: changing {previous} to {meta["provides"]} requires a new authorization revision')
        return updates

    def refresh(self, component_id, instance=None):
        with self._lock:
            record = self._record(component_id)
            if record['state'] != 'running' or (instance and instance != record['instance']):
                return
            instance, component = record['instance'], record['component']
            ticket = record['publication'] = record.get('publication', 0) + 1
        description = deepcopy(validate_description(component.describe()))
        with self._lock:
            if record['state'] != 'running' or record['instance'] != instance or ticket != record['publication']:
                return
            updates = self._contract_updates(record['installation'], description)
            previous = record.get('published', {})
            generations = dict(record['generations'])
            for group in ('events', 'operations'):
                for name, meta in description.get(group, {}).items():
                    key = (group, name)
                    prior = previous.get(group, {}).get(name)
                    if prior is None or handler_signature(meta) != handler_signature(prior):
                        generations[key] = generations.get(key, -1) + 1
                    meta.pop('generation', None)
                    if generations[key]:
                        meta['generation'] = generations[key]
            record['published'] = description
            try:
                if updates:
                    history = {**self._contract_history, **updates}
                    if self._contract_storage:
                        from polaris_platform.persistence import write_json
                        write_json(self._contract_storage, history)
                    self._contract_history = history
                self.refresh_all()
            except Exception:
                record['published'] = previous
                raise
            record['generations'] = generations

    def refresh_all(self):
        with self._lock:
            records = {}
            for target, record in self._records.items():
                if record['state'] != 'running' or 'published' not in record:
                    continue
                description = deepcopy(record['published'])
                for dep in description.get('dependencies', []):
                    if dep.get('kind') in ('startup', 'capability') and not self._dependency_available(dep):
                        operations = description.get('operations', {})
                        for name in dep.get('operations', operations):
                            if name in operations:
                                operations[name].update(available=False, reason=dep)
                records[target] = dict(id=target, installation=record['installation'], instance=record['instance'],
                                       description=description, manifest=record['manifest'])
            graph = DirectoryGraph(records, self._selections)
            if hasattr(self.collaboration, 'replace_directory'):
                self.collaboration.replace_directory(graph)
            else:
                for record in graph.records.values():
                    self.collaboration.advertise(record)
            self._graph = graph

    def _save_selections(self, updates):
        if all(self._selections.get(k) == value for k, value in updates.items()):
            return
        selections = {**self._selections, **updates}
        if self._selection_storage:
            from polaris_platform.persistence import write_json
            write_json(self._selection_storage, selections)
        self._selections = selections
        self.refresh_all()

    def resolved_requirements(self, target, kind, name, instance):
        with self._lock:
            record = self._record(target)
            if record['instance'] != instance or record['state'] != 'running':
                raise PlatformError('stale_instance', target)
            node = (target, kind, name)
            meta = self._graph.nodes.get(node)
            if meta is None:
                raise PlatformError('missing_capability', name)
            if not meta.get('available', True):
                reason = meta.get('reason')
                raise PlatformError('dependency_unavailable', f'{name}: {reason}', reason)
            bindings = meta.get('bindings', {})
            updates = {}
            for alias, binding in bindings.items():
                endpoint = binding.get('endpoint')
                if endpoint and not binding.get('issue'):
                    for key in self._graph.selection_keys[node, alias]:
                        updates[key] = endpoint['installation']
            self._save_selections(updates)
            return deepcopy(bindings)

    def select_provider(self, target, kind, name, alias, installation, consumer_installation):
        if _active.get() is not None:
            raise PlatformError('permission_denied', 'Selecting a provider requires trusted management')
        with self._lock:
            node = (target, kind, name)
            if self._record(target)['installation'] != consumer_installation:
                raise PlatformError('stale_selection', target)
            binding = self._graph.nodes.get(node, {}).get('bindings', {}).get(alias, {})
            if not any(o['installation'] == installation for o in binding.get('candidates', [])):
                raise PlatformError('stale_selection', alias)
            self._save_selections(dict.fromkeys(self._graph.selection_keys[node, alias], installation))

    def status(self, component_id):
        record = self._record(component_id)
        published = self._graph.records.get(component_id)
        if published and record['state'] == 'running':
            description = deepcopy(published['description'])
            if 'view_state' in description:
                description['view_state'] = record['component'].describe().get('view_state', {})
        else:
            description = record['component'].describe() if record['component'] else {}
        return {"id": component_id, **{k: record[k] for k in ("installation", "instance", "state", "error", "manifest")},
                "description": description,
                "dependencies": [dict(d, available=self._dependency_available(d)) for d in description.get('dependencies', [])]}


    def snapshot(self):
        return [self.status(component_id) for component_id in self._records]


def create_runtime():
    return Runtime()
