"""Configuration-only bootstrap, with explicit trusted role bindings."""
import importlib
import json
from pathlib import Path
from .protocol import PlatformError


def invalidate_plugin_modules(manifest, directory, check_only=False, installations=()):
    """Invalidate only a plugin's own entry package, never neighboring plugins."""
    import sys
    if directory is None:
        return
    entry = manifest["entry"]
    if entry["mode"] != "inprocess":
        return
    module = (entry.get("factory") or entry.get("callable") or "").split(":")[0]
    prefix = module.split(".")[0]
    others = [(item["manifest"]["entry"].get("factory") or item["manifest"]["entry"].get("callable") or "").split(":")[0]
              for item in installations if item["manifest"]["id"] != manifest["id"]]
    shared = [name for name in others if name.split(".")[0] == prefix]
    if shared:
        parts = module.split(".")
        # Select the smallest exclusive subtree (pkg.notes for pkg.notes.main
        # beside pkg.labeler.main), preserving the shared parent package.
        for length in range(2, len(parts) + 1):
            candidate = ".".join(parts[:length])
            if all(name != candidate and not name.startswith(candidate + ".") for name in shared):
                prefix = candidate
                break
        else:
            raise PlatformError("restart_required", "Shared entry package updates require a new bootstrap")
        parent = sys.modules.get(prefix.rsplit(".", 1)[0])
        source = getattr(parent, "__file__", None)
        if source and not Path(source).resolve().is_relative_to(Path(directory).resolve()):
            raise PlatformError("restart_required", "Moving an entry in a shared package requires a new bootstrap")
    if module.split(".")[0] == "polaris_platform":
        raise PlatformError("restart_required", "Platform package updates require a new bootstrap")
    root = Path(directory).resolve()
    # A root package already owned by another directory is ambiguous. Never
    # invalidate its modules or silently construct its factory instead.
    if not check_only:
        loaded = sys.modules.get(prefix)
        source = getattr(loaded, "__file__", None)
        if source and not Path(source).resolve().is_relative_to(root):
            raise PlatformError("restart_required", "Entry package is already owned by another plugin directory")
    if check_only:
        return
    for name, loaded in list(sys.modules.items()):
        source = getattr(loaded, "__file__", None)
        if (name == prefix or name.startswith(prefix + ".")) and source and Path(source).resolve().is_relative_to(root):
            del sys.modules[name]
    importlib.invalidate_caches()


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
        if location in sys.path:
            sys.path.remove(location)
        sys.path.insert(0, location)
        # Entry-package source is compiled directly: rapid same-size updates must
        # not reuse timestamp-based bytecode from the previous installation.
        import importlib.abc
        import importlib.machinery
        prefix = module.split(".")[0]
        root = Path(directory).resolve()
        class SourceLoader(importlib.machinery.SourceFileLoader):
            def get_code(self, fullname):
                return self.source_to_code(self.get_data(self.path), self.path)
        class PluginFinder(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname != prefix and not fullname.startswith(prefix + "."):
                    return None
                spec = importlib.machinery.PathFinder.find_spec(fullname, path)
                if spec and spec.origin and spec.origin.endswith(".py") and Path(spec.origin).resolve().is_relative_to(root):
                    spec.loader = SourceLoader(fullname, spec.origin)
                    return spec
                return None
        finder = PluginFinder()
        sys.meta_path.insert(0, finder)
        try:
            factory = getattr(importlib.import_module(module), name)
            kwargs = {}
            for key, value in entry.get("kwargs", {}).items():
                if isinstance(value, dict) and value.get("runtime") is True:
                    value = runtime
                elif isinstance(value, dict) and "component" in value:
                    value = runtime.component_instance(value["component"])
                kwargs[key] = value
            return factory(**kwargs)
        finally:
            sys.meta_path.remove(finder)
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
        if manifest["id"] in runtime.removed_installations():
            continue
        previous = saved_by_id.get(manifest["id"])
        if previous:
            injected = any(isinstance(value, dict) and (value.get("runtime") is True or "component" in value)
                           for value in manifest["entry"].get("kwargs", {}).values())
            if manifest["id"] in runtime.roles.values() or (item.get("trustedBindings") and injected):
                item.update(installationId=previous["installationId"], autostart=previous.get("autostart", False))
            else:
                item = dict(previous)
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
            if component_id not in {item["manifest"]["id"] for item in components}:
                continue
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
