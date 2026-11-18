"""In-memory components with business logic owned by each component."""
from .core import CallContext, ComponentError, ComponentSpec, OperationSpec


def _arguments(args, *, required, optional=()):
    if (not isinstance(args, dict)
            or set(required) - args.keys()
            or args.keys() - set(required) - set(optional)):
        raise ComponentError("invalid_params", "参数缺失或包含未知字段")


def _text(value, field, *, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ComponentError("invalid_params", f"{field} 必须是有效字符串")
    return value


class DocumentsComponent:
    """Own document contents, identifiers, and validation."""

    spec = ComponentSpec(
        id="documents",
        name="文档",
        operations=(
            OperationSpec("create", "write", "创建文档", "title: string, body?: string", "{document: {id, title, body}}"),
            OperationSpec("get", "read", "读取文档", "id: string", "{document: {id, title, body}}"),
            OperationSpec("rename", "write", "修改文档标题", "id: string, title: string", "{document: {id, title, body}}"),
        ),
    )

    def __init__(self):
        self._documents = {}
        self._next_id = 1

    def _find(self, identity):
        _text(identity, "id")
        document = self._documents.get(identity)
        if document is None:
            raise ComponentError("not_found", "文档不存在")
        return document

    def call(self, operation, args, context: CallContext):
        if operation == "create":
            _arguments(args, required=("title",), optional=("body",))
            title = _text(args["title"], "title").strip()
            body = _text(args.get("body", ""), "body", empty=True)
            identity = f"document-{self._next_id}"
            document = {"id": identity, "title": title, "body": body}
            self._documents[identity] = document
            self._next_id += 1
            return {"document": dict(document)}
        if operation == "get":
            _arguments(args, required=("id",))
            return {"document": dict(self._find(args["id"]))}
        if operation == "rename":
            _arguments(args, required=("id", "title"))
            title = _text(args["title"], "title").strip()
            document = self._find(args["id"])
            document["title"] = title
            return {"document": dict(document)}
        raise ComponentError("unknown_operation", "文档操作不存在")


class LabelsComponent:
    """Initiate collaboration through the public document operation."""

    spec = ComponentSpec(
        id="labels",
        name="标签",
        operations=(
            OperationSpec("create_for_document", "write", "按文档标题创建标签", "documentId: string", "{label: {id, documentId, text}}"),
            OperationSpec("list", "read", "列出已创建的标签", "{}", "{labels: [{id, documentId, text}]}"),
        ),
    )

    def __init__(self):
        self._labels = {}
        self._next_id = 1

    def call(self, operation, args, context: CallContext):
        if operation == "list":
            _arguments(args, required=())
            return {"labels": [dict(label) for label in self._labels.values()]}
        if operation == "create_for_document":
            _arguments(args, required=("documentId",))
            identity = _text(args["documentId"], "documentId")
            try:
                result = context.call("documents", "get", {"id": identity})
            except ComponentError as error:
                if error.code == "unknown_component":
                    raise ComponentError("dependency_unavailable", "文档组件不可用，未创建标签") from error
                raise
            document = result["document"]
            label_id = f"label-{self._next_id}"
            label = {"id": label_id, "documentId": document["id"], "text": document["title"]}
            self._labels[label_id] = label
            self._next_id += 1
            return {"label": dict(label)}
        raise ComponentError("unknown_operation", "标签操作不存在")
