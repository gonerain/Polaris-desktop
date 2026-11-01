"""Configuration-only bootstrap, with explicit trusted role bindings."""
import importlib
import json
from pathlib import Path
from .protocol import PlatformError


def load_factory(manifest, directory, runtime, trusted_bindings=False):
    entry = manifest["entry"]
    if entry["mode"] == "process":
        from .transport import ProcessComponent
        return lambda: ProcessComponent(manifest, directory)
    if not trusted_bindings and any(isinstance(value, dict) and (value.get("runtime") is True or "component" in value)
                                    for value in entry.get("kwargs", {}).values()):
        raise PlatformError("untrusted_binding", "Only trusted assembly may inject management or component control ports")
    reference = entry.get("factory") or entry.get("callable")
    if not reference or ":" not in reference:
        raise PlatformError("invalid_manifest", "Inprocess entry requires module:factory")
    module, name = reference.split(":", 1)
    def construct():
        import sys
        location = str(directory)
        if location not in sys.path:
            sys.path.insert(0, location)
        factory = getattr(importlib.import_module(module), name)
        kwargs = {}
        for key, value in entry.get("kwargs", {}).items():
            if isinstance(value, dict) and value.get("runtime") is True:
                value = runtime
            elif isinstance(value, dict) and "component" in value:
                value = runtime.component_instance(value["component"])
            kwargs[key] = value
        return factory(**kwargs)
    return construct


def build(config, base_dir=None, state_dir=None):
    from .runtime import Runtime
    base_dir = Path(base_dir or ".").resolve()
    # The selected manager is the assembly object; alternative managers expose this same control API.
    reference = config.get("managerFactory", "polaris_platform.builtins:create_runtime")
    module, name = reference.split(":", 1)
    runtime = getattr(importlib.import_module(module), name)()
    runtime.roles = dict(config["roles"])
    saved = runtime.load_installations(Path(state_dir) / "installations.json") if state_dir else []
    saved_by_id = {item["manifest"]["id"]: item for item in saved}
    components = []
    configured_ids = set()
    for item in config["components"]:
        item = dict(item)
        directory = (base_dir / (item.get("directory") or ".")).resolve()
        manifest = item.get("manifest") or json.loads((directory / "manifest.json").read_text())
        item.update(manifest=manifest, directory=str(directory))
        previous = saved_by_id.get(manifest["id"])
        if previous:
            item.update(installationId=previous["installationId"], autostart=previous.get("autostart", False))
        configured_ids.add(manifest["id"])
        components.append(item)
    components.extend(item for item in saved if item["manifest"]["id"] not in configured_ids)
    for specification in components:
        directory = (base_dir / (specification.get("directory") or ".")).resolve()
        manifest = specification.get("manifest")
        if manifest is None:
            manifest = json.loads((directory / "manifest.json").read_text())
        role = next((r for r, target in runtime.roles.items() if target == manifest["id"]), None)
        if role == "runtime":
            factory = lambda: runtime
        else:
            factory = load_factory(manifest, directory, runtime, specification.get("trustedBindings", False))
        runtime.install(manifest, factory, specification.get("installationId"), directory, specification.get("autostart", False), specification.get("trustedBindings", False))
    # Construct foundation before lifecycle start; bind only configured control ports.
    for role in ("authorization", "collaboration"):
        runtime.prepare(runtime.roles[role])
    runtime.connect(runtime.component_instance(runtime.roles["collaboration"]),
                    runtime.component_instance(runtime.roles["authorization"]))
    required = set(config.get("required", list(runtime.roles.values())))
    order = list(config.get("start", [runtime.roles[r] for r in ("authorization", "collaboration", "runtime")]))
    for specification in components:
        identity = specification["manifest"]["id"]
        if specification.get("autostart") and identity not in order:
            order.append(identity)
    started = []
    try:
        for component_id in order:
            specification = next(item for item in components if item["manifest"]["id"] == component_id)
            if specification["manifest"]["entry"].get("defer"):
                continue
            if component_id not in required and component_id in saved_by_id and not specification.get("autostart"):
                continue
            try:
                runtime.start_component(component_id)
                started.append(component_id)
            except Exception:
                if component_id in required:
                    raise
        if state_dir is not None:
            runtime.configure_storage(state_dir)
        if not saved:
            for grant in config.get("grants", []):
                runtime.grant(**grant)
    except Exception:
        import sys
        for identity in reversed(started):
            try:
                runtime.stop_component(identity, persist=False)
            except Exception:
                try:
                    runtime.stop_component(identity, force=True, persist=False)
                except Exception as cleanup_error:
                    print(f"Bootstrap cleanup failed for {identity}: {cleanup_error}", file=sys.stderr)
        raise
    return runtime


def from_file(path, state_dir=None):
    path = Path(path).resolve()
    return build(json.loads(path.read_text()), path.parent, state_dir)


def default_config():
    """Minimal headless distribution assembly, also available after wheel installation."""
    roles = {name: name for name in ("authorization", "collaboration", "runtime")}
    return {"roles": roles, "required": list(roles), "start": list(roles),
            "components": [{"manifest": {"id": name, "name": name.title(), "version": "0.1.0",
                "platformApi": 1, "entry": {"mode": "inprocess", "factory": f"polaris_platform.builtins:create_{name}"}}}
                for name in roles]}
