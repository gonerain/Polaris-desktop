"""Behavioral contracts for the isolated, Qt-free component layer prototype."""
from dataclasses import dataclass, FrozenInstanceError
from decimal import Decimal
from pathlib import Path
import subprocess
import sys
import unittest

from prototypes.component_layer.core import (
    ComponentError, ComponentSpec, OperationSpec, Registry,
)
from prototypes.component_layer.examples import DocumentsComponent, LabelsComponent


def operation(name, access="read", version=1):
    return OperationSpec(name, access, name, version=version)


class RecordingComponent:
    def __init__(self, identity, operations=None, target=None):
        self.spec = ComponentSpec(identity, identity, tuple(operations or [operation("get")]))
        self.target = target
        self.calls = []
        self.result = {"nested": {"values": ["original"]}}

    def call(self, name, args, context):
        self.calls.append((name, args, context))
        if self.target:
            return context.call(*self.target, args)
        if "nested" in args:
            args["nested"]["values"].append("handled")
        return self.result


class ComponentLayerTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry()

    def context(self, *operations, source="test", principal="alice", request="request-1"):
        grant = self.registry.issue_grant(
            principal=principal, source=source, operations=list(operations))
        return self.registry.context(grant, request)

    def assert_code(self, code, callback):
        with self.assertRaises(ComponentError) as error:
            callback()
        self.assertEqual(error.exception.code, code)

    def test_discovery_tracks_registration_and_exposes_immutable_contracts(self):
        first = RecordingComponent("first")
        second = RecordingComponent("second")
        self.assertEqual(self.registry.discover(), ())
        self.registry.register(first)
        self.registry.register(second)
        discovered = self.registry.discover()
        self.assertIsInstance(discovered, tuple)
        self.assertEqual({spec.id for spec in discovered}, {"first", "second"})
        with self.assertRaises(FrozenInstanceError):
            discovered[0].name = "changed"
        with self.assertRaises(FrozenInstanceError):
            discovered[0].operations[0].access = "write"
        self.registry.unregister("first")
        self.assertEqual(tuple(spec.id for spec in self.registry.discover()), ("second",))
        self.assert_code("unknown_component", lambda: self.registry.help("first"))
        self.assert_code("unknown_component", lambda: self.registry.unregister("first"))

    def test_registration_captures_metadata_instead_of_observing_provider_mutation(self):
        operations = [operation("get")]
        component = RecordingComponent("sample")
        component.spec = ComponentSpec("sample", "Original", operations)
        self.registry.register(component)
        context = self.context(("sample", "get"))
        operations.append(operation("erase", "write"))
        component.spec = ComponentSpec("sample", "Reassigned", (operation("erase", "write"),))
        snapshot = self.registry.help("sample")
        self.assertEqual(snapshot.name, "Original")
        self.assertEqual(tuple(op.name for op in snapshot.operations), ("get",))
        self.assertEqual(context.call("sample", "get", {}), component.result)
        self.assert_code("unknown_operation", lambda: context.call("sample", "erase", {}))

    def test_invalid_registration_or_update_preserves_existing_provider_and_authority(self):
        original = RecordingComponent("sample")
        self.registry.register(original)
        context = self.context(("sample", "get"))
        before = self.registry.discover()

        class MissingCall:
            def __init__(self, identity):
                self.spec = ComponentSpec(identity, identity, (operation("get"),))

        for action, identity in ((self.registry.register, "new"), (self.registry.update, "sample")):
            candidates = (
                RecordingComponent(identity, [operation("get"), operation("get")]),
                MissingCall(identity),
            )
            for candidate in candidates:
                with self.subTest(action=action.__name__, candidate=type(candidate).__name__):
                    self.assert_code("invalid_contract", lambda: action(candidate))
                    self.assertEqual(self.registry.discover(), before)
                    self.assertEqual(context.call("sample", "get", {}), original.result)
        self.assertEqual(len(original.calls), 4)

    def test_components_define_public_data_types_and_validate_their_own_arguments(self):
        @dataclass(frozen=True)
        class AmountRequest:
            amount: Decimal

        @dataclass(frozen=True)
        class AmountResult:
            total: Decimal

        class AmountComponent:
            spec = ComponentSpec("amounts", "Amounts", (
                OperationSpec("calculate", "read", "Calculate an amount", "AmountRequest", "AmountResult"),
            ))

            def call(self, name, args, context):
                self.received = args
                if not isinstance(args, AmountRequest) or not isinstance(args.amount, Decimal):
                    raise ComponentError("invalid_params", "Amounts requires an AmountRequest containing Decimal")
                self.result = AmountResult(args.amount * Decimal("1.25"))
                return self.result

        component = AmountComponent()
        self.registry.register(component)
        context = self.context(("amounts", "calculate"))
        request = AmountRequest(Decimal("12.40"))
        result = context.call("amounts", "calculate", request)
        self.assertIs(component.received, request)
        self.assertIs(result, component.result)
        self.assertEqual(result, AmountResult(Decimal("15.5000")))
        invalid_request = {"amount": Decimal("12.40")}
        with self.assertRaises(ComponentError) as error:
            context.call("amounts", "calculate", invalid_request)
        self.assertEqual(error.exception.code, "invalid_params")
        self.assertEqual(str(error.exception), "Amounts requires an AmountRequest containing Decimal")
        self.assertIs(component.received, invalid_request)

    def test_grant_captures_explicit_operations_and_not_the_input_list(self):
        component = RecordingComponent("sample", [operation("get"), operation("erase", "write")])
        self.registry.register(component)
        allowed = [("sample", "get")]
        grant = self.registry.issue_grant(principal="alice", source="test", operations=allowed)
        allowed.append(("sample", "erase"))
        context = self.registry.context(grant, "request-1")
        context.call("sample", "get", {})
        self.assert_code("permission_denied", lambda: context.call("sample", "erase", {}))
        self.assertEqual([call[0] for call in component.calls], ["get"])

    def test_update_invalidates_only_the_updated_component_and_does_not_grant_new_operations(self):
        sample = RecordingComponent("sample")
        other = RecordingComponent("other")
        self.registry.register(sample)
        self.registry.register(other)
        context = self.context(("sample", "get"), ("other", "get"))
        replacement = RecordingComponent("sample", [operation("get"), operation("erase", "write")])
        self.registry.update(replacement)
        self.assertEqual(tuple(op.name for op in self.registry.help("sample").operations), ("get", "erase"))
        self.assert_code("permission_denied", lambda: context.call("sample", "get", {}))
        self.assert_code("permission_denied", lambda: context.call("sample", "erase", {}))
        self.assertEqual(context.call("other", "get", {}), other.result)
        self.assertFalse(replacement.calls)
        self.context(("sample", "erase")).call("sample", "erase", {})
        self.assertEqual(len(replacement.calls), 1)

    def test_operation_version_change_requires_new_authorization(self):
        self.registry.register(RecordingComponent("sample", [operation("get", version=1)]))
        context = self.context(("sample", "get"))
        replacement = RecordingComponent("sample", [operation("get", version=2)])
        self.registry.update(replacement)
        self.assert_code("permission_denied", lambda: context.call("sample", "get", {}))
        self.assertFalse(replacement.calls)
        self.context(("sample", "get")).call("sample", "get", {})

    def test_unregister_then_reregister_does_not_revive_old_authorization(self):
        component = RecordingComponent("sample")
        self.registry.register(component)
        context = self.context(("sample", "get"))
        self.registry.unregister("sample")
        self.assert_code("unknown_component", lambda: context.call("sample", "get", {}))
        self.registry.register(component)
        self.assert_code("permission_denied", lambda: context.call("sample", "get", {}))
        self.assertFalse(component.calls)

    def test_narrowing_cannot_restore_removed_or_ungranted_operations(self):
        self.registry.register(RecordingComponent("sample", [operation("get"), operation("erase", "write")]))
        context = self.context(("sample", "get"), ("sample", "erase"))
        narrowed = context.narrow([("sample", "get")])
        narrowed.call("sample", "get", {})
        self.assert_code("permission_denied", lambda: narrowed.call("sample", "erase", {}))
        self.assert_code("permission_denied", lambda: narrowed.narrow([("sample", "erase")]))
        empty = narrowed.narrow([])
        self.assert_code("permission_denied", lambda: empty.call("sample", "get", {}))
        context.call("sample", "erase", {})

    def test_nested_calls_preserve_authority_and_record_the_actual_call_chain(self):
        leaf = RecordingComponent("leaf")
        relay = RecordingComponent("relay", target=("leaf", "get"))
        self.registry.register(relay)
        self.registry.register(leaf)
        context = self.context(("relay", "get"), ("leaf", "get"), source="window", request="request-42")
        context.call("relay", "get", {})
        received = leaf.calls[0][2]
        self.assertEqual((received.principal, received.source, received.request_id), ("alice", "window", "request-42"))
        self.assertEqual(received.call_chain, (("relay", "get"), ("leaf", "get")))
        self.assertEqual(relay.calls[0][2].call_chain, (("relay", "get"),))
        self.assertEqual(context.call_chain, ())

    def test_nested_calls_cannot_borrow_the_target_components_capabilities(self):
        leaf = RecordingComponent("leaf")
        relay = RecordingComponent("relay", target=("leaf", "get"))
        self.registry.register(relay)
        self.registry.register(leaf)
        context = self.context(("relay", "get"))
        self.assert_code("permission_denied", lambda: context.call("relay", "get", {}))
        self.assertFalse(leaf.calls)

    def test_same_principal_with_different_authorization_sources_stays_independent(self):
        component = RecordingComponent("sample", [operation("get"), operation("erase", "write")])
        self.registry.register(component)
        local = self.context(("sample", "get"), ("sample", "erase"), source="local")
        remote = self.context(("sample", "get"), source="remote")
        local.call("sample", "erase", {})
        remote.call("sample", "get", {})
        self.assert_code("permission_denied", lambda: remote.call("sample", "erase", {}))
        self.assertEqual([call[2].source for call in component.calls], ["local", "remote"])

    def test_revocation_applies_to_existing_contexts_and_their_narrowed_children(self):
        component = RecordingComponent("sample")
        self.registry.register(component)
        grant = self.registry.issue_grant(principal="alice", source="test", operations=[("sample", "get")])
        context = self.registry.context(grant, "request-1")
        narrowed = context.narrow([("sample", "get")])
        context.call("sample", "get", {})
        self.registry.revoke(grant)
        self.assert_code("permission_denied", lambda: context.call("sample", "get", {}))
        self.assert_code("permission_denied", lambda: narrowed.call("sample", "get", {}))
        self.assertEqual(len(component.calls), 1)

    def test_prototype_imports_without_qt_or_existing_business_modules(self):
        script = '''
import importlib.abc
import sys
class Unavailable(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"PySide6", "polaris"}:
            raise ImportError("Not available in component prototype: " + fullname)
sys.meta_path.insert(0, Unavailable())
from prototypes.component_layer.core import Registry
from prototypes.component_layer.examples import DocumentsComponent, LabelsComponent
registry = Registry()
registry.register(DocumentsComponent())
registry.register(LabelsComponent())
assert len(registry.discover()) == 2
'''
        result = subprocess.run([sys.executable, "-B", "-c", script],
                                cwd=Path(__file__).resolve().parent.parent,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class ExampleComponentTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry()
        self.documents = DocumentsComponent()
        self.labels = LabelsComponent()
        self.registry.register(self.documents)
        self.registry.register(self.labels)
        grant = self.registry.issue_grant(principal="alice", source="test", operations=[
            ("documents", "create"), ("documents", "get"), ("documents", "rename"),
            ("labels", "create_for_document"), ("labels", "list"),
        ])
        self.context = self.registry.context(grant, "examples")

    def assert_code(self, code, callback):
        with self.assertRaises(ComponentError) as error:
            callback()
        self.assertEqual(error.exception.code, code)

    def create_document(self, title="Original"):
        return self.context.call("documents", "create", {"title": title, "body": "Body"})["document"]

    def test_examples_collaborate_through_public_operations(self):
        document = self.create_document()
        self.assertEqual(document["body"], "Body")
        renamed = self.context.call("documents", "rename", {"id": document["id"], "title": "Updated"})["document"]
        self.assertEqual(renamed["title"], "Updated")
        label = self.context.call("labels", "create_for_document", {"documentId": document["id"]})["label"]
        self.assertEqual(label["documentId"], document["id"])
        self.assertEqual(label["text"], "Updated")
        self.assertEqual(self.context.call("labels", "list", {}), {"labels": [label]})

    def test_example_components_own_their_returned_copy_contracts(self):
        document = self.create_document()
        expected_document = dict(document)
        identity = document["id"]
        document.update(id="changed", title="Changed by caller", body="Changed body")
        fetched = self.context.call("documents", "get", {"id": identity})["document"]
        self.assertEqual(fetched, expected_document)
        fetched["body"] = "Changed fetched body"
        renamed = self.context.call("documents", "rename", {"id": identity, "title": "Updated"})["document"]
        expected_document["title"] = "Updated"
        self.assertEqual(renamed, expected_document)
        renamed["title"] = "Changed renamed title"
        self.assertEqual(self.context.call("documents", "get", {"id": identity})["document"], expected_document)

        label = self.context.call("labels", "create_for_document", {"documentId": identity})["label"]
        expected_label = dict(label)
        label.update(id="changed", documentId="changed", text="Changed by caller")
        listed = self.context.call("labels", "list", {})
        self.assertEqual(listed, {"labels": [expected_label]})
        listed["labels"][0]["text"] = "Changed listed text"
        listed["labels"].clear()
        self.assertEqual(self.context.call("labels", "list", {}), {"labels": [expected_label]})

    def test_public_contract_allows_different_document_storage_without_changing_labels(self):
        document = self.create_document()
        first_label = self.context.call("labels", "create_for_document", {"documentId": document["id"]})["label"]
        get_contract = next(op for op in self.registry.help("documents").operations if op.name == "get")

        class TupleBackedDocuments:
            spec = ComponentSpec("documents", "Tuple-backed documents", (get_contract,))

            def __init__(self, identity):
                self.rows = ((identity, b"Replacement title", b"Replacement body"),)

            def call(self, name, args, context):
                if name != "get":
                    raise ComponentError("unknown_operation", "Unknown operation")
                if set(args) != {"id"} or not isinstance(args["id"], str):
                    raise ComponentError("invalid_params", "Expected document id")
                row = next((row for row in self.rows if row[0] == args["id"]), None)
                if row is None:
                    raise ComponentError("not_found", "Document not found")
                return {"document": {"id": row[0], "title": row[1].decode(), "body": row[2].decode()}}

        self.registry.update(TupleBackedDocuments(document["id"]))
        grant = self.registry.issue_grant(principal="alice", source="test", operations=[
            ("documents", "get"), ("labels", "create_for_document"), ("labels", "list"),
        ])
        context = self.registry.context(grant, "after-replacement")
        second_label = context.call("labels", "create_for_document", {"documentId": document["id"]})["label"]
        self.assertEqual(second_label["documentId"], document["id"])
        self.assertEqual(second_label["text"], "Replacement title")
        self.assertNotEqual(second_label["id"], first_label["id"])
        self.assertEqual(context.call("labels", "list", {}), {"labels": [first_label, second_label]})

    def test_dependency_exit_does_not_disable_independent_label_reads(self):
        document = self.create_document()
        label = self.context.call("labels", "create_for_document", {"documentId": document["id"]})["label"]
        self.registry.unregister("documents")
        self.assertEqual(self.context.call("labels", "list", {}), {"labels": [label]})
        self.assert_code("dependency_unavailable", lambda: self.context.call(
            "labels", "create_for_document", {"documentId": document["id"]}))
        self.assertEqual(self.context.call("labels", "list", {}), {"labels": [label]})

    def test_failed_dependency_authorization_does_not_create_a_label(self):
        document = self.create_document()
        context = self.context.narrow([("labels", "create_for_document"), ("labels", "list")])
        self.assert_code("permission_denied", lambda: context.call(
            "labels", "create_for_document", {"documentId": document["id"]}))
        self.assertEqual(context.call("labels", "list", {}), {"labels": []})

    def test_component_parameter_validation_precedes_its_own_mutation(self):
        self.assert_code("invalid_params", lambda: self.context.call("documents", "create", {"title": ""}))
        document = self.create_document()
        self.assert_code("invalid_params", lambda: self.context.call(
            "documents", "rename", {"id": document["id"], "title": ""}))
        self.assertEqual(self.context.call("documents", "get", {"id": document["id"]})["document"], document)
        self.assertEqual(self.context.call("labels", "list", {}), {"labels": []})


if __name__ == "__main__":
    unittest.main()
