"""Exact capability grants, separately recorded for interactive/background use."""
from threading import RLock
from .component import Component
from .protocol import PlatformError


class Authorization(Component):
    def __init__(self):
        super().__init__()
        self._lock = RLock()
        self._grants = {}
        self._identities = {}
        self._labels = {}
        self._running = False
        self._storage = None
        self.operation("decisions")(lambda p, c: self.decisions())

    def start(self, port):
        super().start(port)
        self._running = True

    def stop(self):
        self._running = False
        super().stop()

    def require_running(self):
        if not self._running:
            raise PlatformError("unavailable", "Authorization is stopped")

    def bind_identity(self, requester, installation):
        with self._lock:
            self._identities[requester] = installation
            self._labels[installation] = requester

    def _identity(self, requester):
        return self._identities.get(requester, requester)

    def grant(self, requester, key, background=False):
        self.require_running()
        with self._lock:
            self._grants.setdefault((self._identity(requester), bool(background)), set()).add(key)
            self._persist()

    def revoke(self, requester, key, background=False):
        self.require_running()
        with self._lock:
            self._grants.get((self._identity(requester), bool(background)), set()).discard(key)
            self._persist()

    def scope(self, requester, background=False):
        self.require_running()
        with self._lock:
            return frozenset(self._grants.get((self._identity(requester), bool(background)), set()))

    def check(self, context, key):
        self.require_running()
        if context.origin_installation != self._identity(context.origin):
            raise PlatformError("invalid_context", "Request installation identity has changed")
        if key not in context.scope or key not in self.scope(context.origin, context.source == "background"):
            raise PlatformError("permission_required", "Explicit permission required", {"requester": context.origin, "capability": list(key)})

    def decisions(self):
        with self._lock:
            return [{"requester": self._labels.get(r, r), "requesterInstallation": r, "background": b, "scope": [list(k) for k in keys]}
                    for (r, b), keys in self._grants.items()]

    def export_records(self):
        return self.decisions()

    def import_records(self, records):
        with self._lock:
            for record in records:
                installation = record.get("requesterInstallation")
                if installation is None:
                    continue  # Unbound legacy records cannot prove installation ownership.
                self._labels[installation] = record["requester"]
                self._grants[(installation, record["background"])] = {tuple(k) for k in record["scope"]}
            self._persist()

    def configure_storage(self, path):
        from .persistence import read_json
        with self._lock:
            self._storage = path
            self.import_records(read_json(path, []))
            self._persist()

    def _persist(self):
        if self._storage is not None:
            from .persistence import write_json
            write_json(self._storage, self.export_records())
