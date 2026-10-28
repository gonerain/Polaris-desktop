"""Explicit, source-neutral desktop pet speech. No chat forwarding or audio."""
from .component_api import ApiError, arguments, text


class PetAPI:
    name = "桌宠"
    operations = [{
        "name": "say", "access": "write",
        "description": "让桌宠弹出纯文字气泡；画布展开时显示界面内短提示。不播放声音、不切换页面、不转发聊天。新消息替换旧消息。",
        "parameters": {"text": "非空短消息，最多120字符，显示不下会省略", "durationMs?": "整数1000..15000，默认6500"},
        "returns": "{shown,presentation,durationMs}；presentation为bubble或inline",
        "example": {"text": "Hi！👋", "durationMs": 6500},
    }]

    def __init__(self, window):
        self._window = window

    def call(self, operation, args):
        if operation != "say":
            raise ApiError("unknown_operation", "操作未登记")
        arguments(args, ("text", "durationMs"), ("text",))
        message = text(args["text"], "text", 120).strip()
        if any(ord(char) < 32 and char != "\n" for char in message):
            raise ApiError("invalid_params", "消息不能含控制字符")
        duration = args.get("durationMs", 6500)
        if type(duration) is not int or not 1000 <= duration <= 15000:
            raise ApiError("invalid_params", "durationMs 必须是1000..15000的整数")
        if not self._window.isVisible():
            raise ApiError("display_unavailable", "桌宠窗口不可见，未显示消息")
        presentation = self._window.showSpeech(message, duration)
        if presentation not in ("bubble", "inline"):
            raise ApiError("display_unavailable", "无法显示消息")
        return {"shown": True, "presentation": presentation, "durationMs": duration}
