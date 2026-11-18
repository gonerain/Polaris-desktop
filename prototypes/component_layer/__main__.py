"""Run with python -m prototypes.component_layer."""
import json

from .core import ComponentError, Registry
from .examples import DocumentsComponent, LabelsComponent


def _show(label, value):
    print(f"{label}：{json.dumps(value, ensure_ascii=False)}")


def main():
    registry = Registry()
    registry.register(DocumentsComponent())
    registry.register(LabelsComponent())
    _show("已发现组件", [component.id for component in registry.discover()])

    # The host explicitly grants each operation used by the initiating request.
    grant = registry.issue_grant(
        principal="demo-user",
        source="demo-host",
        operations=[("documents", "create"), ("documents", "get"),
                    ("labels", "create_for_document"), ("labels", "list")],
    )
    context = registry.context(grant, request_id="demo-request")
    document = context.call("documents", "create", {"title": "设计记录", "body": "组件通过公开操作协作。"})
    _show("创建文档", document)
    document_id = document["document"]["id"]
    _show("创建标签", context.call("labels", "create_for_document", {"documentId": document_id}))

    restricted = context.narrow([("labels", "create_for_document")])
    try:
        restricted.call("labels", "create_for_document", {"documentId": document_id})
    except ComponentError as error:
        _show("缺少文档读取授权", {"code": error.code})

    registry.unregister("documents")
    _show("文档注销后的标签", context.call("labels", "list", {}))
    try:
        context.call("labels", "create_for_document", {"documentId": document_id})
    except ComponentError as error:
        _show("文档注销后创建标签", {"code": error.code})


if __name__ == "__main__":
    main()
