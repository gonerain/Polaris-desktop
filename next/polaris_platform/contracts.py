"""Contract declarations and resolution on a single directory snapshot."""
from collections import defaultdict
from copy import deepcopy
import json
import re

from .protocol import PlatformError, capability


CONTRACT = re.compile(r'[A-Za-z][\w-]*(?:\.[A-Za-z][\w-]*)+@([1-9][0-9]*)', re.ASCII)
GROUPS = {'operation': 'operations', 'event': 'events'}


def contract_version(value):
    match = CONTRACT.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise PlatformError('invalid_description', f'Expected a namespaced contract with @major: {value!r}')
    return int(match[1])


def requirements(metadata):
    result = {}
    raw = metadata.get('requires', {})
    if not isinstance(raw, dict):
        raise PlatformError('invalid_description', 'requires must map aliases to contracts')
    for alias, value in raw.items():
        spec = {'contract': value} if isinstance(value, str) else value
        if not isinstance(alias, str) or not alias or not isinstance(spec, dict):
            raise PlatformError('invalid_description', 'Invalid requirement alias or description')
        contract_version(spec.get('contract'))
        spec = {'kind': 'operation', 'access': 'read', 'optional': False, **spec}
        if (spec['kind'] not in ('operation', 'event') or spec['access'] not in ('read', 'write')
                or type(spec['optional']) is not bool or ('group' in spec and not isinstance(spec['group'], str))
                or ('target' in spec and not isinstance(spec['target'], str))
                or set(spec) - {'kind', 'contract', 'access', 'optional', 'group', 'target'}):
            raise PlatformError('invalid_description', f'Invalid requirement {alias}')
        result[alias] = spec
    return result


def validate_contracts(description):
    for kind, group in GROUPS.items():
        published = set()
        for name, meta in description.get(group, {}).items():
            if 'provides' in meta:
                contract = meta['provides']
                if contract_version(contract) != meta.get('major', 1) or contract in published:
                    raise PlatformError('invalid_description', f'Invalid version or duplicate {kind} contract on {name}')
                published.add(contract)
            requirements(meta)


def selection_key(record, kind, name, alias, spec):
    # Persist intent across compatible updates, but never across a reinstall or contract change.
    return json.dumps([record['installation'], kind, name, alias, spec['contract'], spec['kind'], spec['access']],
                      ensure_ascii=False, separators=(',', ':'))


class DirectoryGraph:
    def __init__(self, records, selections):
        self.records = deepcopy(records)
        self.nodes = {}
        self.index = defaultdict(dict)
        self.selections = selections
        self.selection_keys = {}
        for target, record in self.records.items():
            for kind, plural in GROUPS.items():
                for name, meta in record['description'].get(plural, {}).items():
                    node = (target, kind, name)
                    meta.pop('bindings', None)  # Computed by the host; never accept provider-supplied endpoints.
                    self.nodes[node] = meta
                    if 'provides' in meta:
                        self.index[meta['provides'], kind, meta.get('access', 'read')][target] = node
        self.edges = {}
        declared = {node: meta.get('reason', {'code': 'unavailable'})
                    for node, meta in self.nodes.items() if not meta.get('available', True)}
        unavailable = set(declared)
        # A fork with one healthy provider can resolve after a downstream failure is known.
        # An undecided fork remains a candidate until the user actually makes a selection.
        while True:
            self.edges.clear()
            for node, meta in self.nodes.items():
                if node not in declared:
                    meta.pop('available', None)
                    meta.pop('reason', None)
                if meta.get('requires'):
                    self._bind(node, meta, unavailable)
            reasons = self._availability()
            blocked = {n for n, reason in reasons.items() if reason and
                       (not isinstance(reason, dict) or reason.get('code') != 'selection_required')}
            if blocked <= unavailable:
                break
            unavailable.update(blocked)

    def _bind(self, node, meta, unavailable):
        groups = defaultdict(dict)
        for alias, spec in requirements(meta).items():
            # An ungrouped alias cannot collide with a user-supplied group name.
            groups[('group', spec['group']) if spec.get('group') else ('alias', alias)][alias] = spec
        bindings = meta['bindings'] = {}
        for members in groups.values():
            bindings.update(self._resolve_group(node, members, unavailable))

    def _resolve_group(self, node, members, unavailable):
        target, kind, name = node
        matches = {}
        for alias, spec in members.items():
            providers = self.index[spec['contract'], spec['kind'], spec['access']]
            if 'target' in spec:
                providers = {t: entry for t, entry in providers.items() if t == spec['target']}
            matches[alias] = providers
        required = [alias for alias, spec in members.items() if not spec['optional']]
        if required:
            candidates = set.intersection(*(set(matches[alias]) for alias in required))
        else:
            candidates = set.union(*(set(providers) for providers in matches.values()))
        keys = {alias: selection_key(self.records[target], kind, name, alias, spec)
                for alias, spec in members.items()}
        saved = {self.selections[key] for key in keys.values() if key in self.selections}
        eligible = [t for t in sorted(candidates) if not saved or saved == {self.records[t]['installation']}]
        if not saved and len(eligible) > 1:
            ready = [t for t in eligible if all(matches[alias][t] not in unavailable for alias in required)]
            eligible = ready or eligible
        selected = eligible[0] if len(eligible) == 1 else None
        options = [{'target': t, 'installation': self.records[t]['installation']} for t in sorted(candidates)]
        missing = next((members[a] for a in required if not matches[a]), None)
        bindings = {}
        for alias, spec in members.items():
            self.selection_keys[node, alias] = tuple(keys.values())
            binding = bindings[alias] = dict(spec, candidates=options)
            endpoint = matches[alias].get(selected)
            if endpoint:
                provider, dep_kind, local = endpoint
                rec, meta = self.records[provider], self.nodes[endpoint]
                binding['endpoint'] = dict(target=provider, instance=rec['instance'], installation=rec['installation'],
                                           kind=dep_kind, name=local, generation=meta.get('generation', 0),
                                           key=list(capability(rec['installation'], dep_kind, local, meta)))
                self.edges[node, alias] = endpoint
            else:
                binding['issue'] = self._missing(missing or spec, saved, eligible,
                                                 split=bool(required and not missing and not candidates))
        return bindings

    def _missing(self, spec, saved, eligible, split):
        contract = spec['contract']
        versions = sorted({c for (c, kind, access), providers in self.index.items() if providers
                           and kind == spec['kind'] and access == spec['access']
                           and c.split('@')[0] == contract.split('@')[0]})
        if versions and contract not in versions:
            return dict(code='incompatible_version', contract=contract, offered=versions)
        if split:
            return dict(code='no_common_provider', contract=contract)
        if saved and not eligible:
            return dict(code='selected_provider_unavailable', contract=contract, installations=sorted(saved))
        code = 'selection_required' if len(eligible) > 1 else 'missing_contract'
        return dict(code=code, contract=contract)

    def _availability(self):
        # Visit required edges only; an optional edge can never make its consumer unavailable.
        completed = {}
        def visit(node, path):
            if node in completed:
                return completed[node]
            if node in path:
                return dict(code='dependency_cycle', path=[list(n) for n in path[path.index(node):] + [node]])
            meta = self.nodes[node]
            reason = None if meta.get('available', True) else meta.get('reason', {'code': 'unavailable'})
            for alias, binding in meta.get('bindings', {}).items():
                if reason or binding['optional']:
                    continue
                edge = self.edges.get((node, alias))
                reason = visit(edge, path + [node]) if edge else binding['issue']
            completed[node] = reason
            if reason:
                meta.update(available=False, reason=reason)
            return reason
        for node in self.nodes:
            visit(node, [])
        for (node, alias), edge in self.edges.items():
            if completed[edge]:
                self.nodes[node]['bindings'][alias]['issue'] = completed[edge]
        return completed
