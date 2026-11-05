# 微信助手看到的 Agent 操作说明

按本机当前安装的 Agent、微信组件代码及微信保存的操作允许列表重建 `help` 返回，并经过实际的工具结果裁剪函数。这是当前配置下的重建结果，不是此前某轮对话的抓包。未启动组件服务、调用模型或执行任何业务操作。

## 模型调用的工具

```json
{
  "name": "help",
  "arguments": {
    "component": "org.polaris.agent"
  }
}
```

## 模型收到的工具返回

以下仅增加 JSON 缩进，字段和文案保持原样。

```json
{
  "id": "org.polaris.agent",
  "name": "Agent",
  "description": {
    "operations": {
      "get": {
        "access": "read",
        "major": 1,
        "revision": 1,
        "interface": null,
        "title": "查看概况",
        "description": "返回会话和投递记录。",
        "parameters": {
          "type": "object",
          "properties": {},
          "required": [],
          "additionalProperties": false
        }
      },
      "sessions": {
        "access": "read",
        "major": 1,
        "revision": 1,
        "interface": null,
        "title": "列出会话",
        "description": "返回会话列表，包含 id、标题、在线状态和 marked。",
        "parameters": {
          "type": "object",
          "properties": {},
          "required": [],
          "additionalProperties": false
        }
      },
      "status": {
        "access": "read",
        "major": 1,
        "revision": 1,
        "interface": null,
        "title": "查看会话状态",
        "description": "返回指定会话详情。",
        "parameters": {
          "type": "object",
          "properties": {
            "session_id": {
              "type": "string",
              "description": "sessions 返回的完整 id 字段；不是 sessionId、标题或后缀。先列出会话，按用户描述匹配，再传入 id。"
            }
          },
          "required": [
            "session_id"
          ],
          "additionalProperties": false
        }
      },
      "result": {
        "access": "read",
        "major": 1,
        "revision": 1,
        "interface": null,
        "title": "查看运行结果",
        "description": "不指定 run_id 时返回该会话最近一次运行。",
        "parameters": {
          "type": "object",
          "properties": {
            "session_id": {
              "type": "string",
              "description": "sessions 返回的完整 id 字段；不是 sessionId、标题或后缀。先列出会话，按用户描述匹配，再传入 id。"
            },
            "run_id": {
              "type": "string"
            }
          },
          "required": [
            "session_id"
          ],
          "additionalProperties": false
        }
      },
      "delivery": {
        "access": "read",
        "major": 1,
        "revision": 1,
        "interface": null,
        "title": "查看投递状态",
        "description": "查询 send 返回的投递记录。pending=本机排队待确认；accepted=宿主已接收，仍不代表运行完成；rejected=宿主拒绝；unknown=结果未知。",
        "parameters": {
          "type": "object",
          "properties": {
            "delivery_id": {
              "type": "string"
            }
          },
          "required": [
            "delivery_id"
          ],
          "additionalProperties": false
        }
      },
      "mark": {
        "access": "write",
        "major": 1,
        "revision": 1,
        "interface": null,
        "title": "标记会话",
        "description": "标记已有会话并返回会话记录；marked=true 表示标记成功。",
        "parameters": {
          "type": "object",
          "properties": {
            "session_id": {
              "type": "string",
              "description": "sessions 返回的完整 id 字段；不是 sessionId、标题或后缀。先列出会话，按用户描述匹配，再传入 id。"
            }
          },
          "required": [
            "session_id"
          ],
          "additionalProperties": false
        }
      },
      "unmark": {
        "access": "write",
        "major": 1,
        "revision": 1,
        "interface": null,
        "title": "取消标记",
        "description": "取消会话标记并返回会话记录。",
        "parameters": {
          "type": "object",
          "properties": {
            "session_id": {
              "type": "string",
              "description": "sessions 返回的完整 id 字段；不是 sessionId、标题或后缀。先列出会话，按用户描述匹配，再传入 id。"
            }
          },
          "required": [
            "session_id"
          ],
          "additionalProperties": false
        }
      },
      "send": {
        "access": "write",
        "major": 1,
        "revision": 1,
        "interface": null,
        "title": "发送消息",
        "description": "仅向已标记、在线且 canSend=true 的会话提交消息。返回 pending 只表示已提交、等待宿主确认，不能说已送达或新一轮已开始；用 delivery 确认接收，再用 result 确认运行结果。",
        "parameters": {
          "type": "object",
          "properties": {
            "session_id": {
              "type": "string",
              "description": "sessions 返回的完整 id 字段；不是 sessionId、标题或后缀。先列出会话，按用户描述匹配，再传入 id。"
            },
            "text": {
              "type": "string"
            },
            "mode": {
              "type": "string",
              "enum": [
                "start",
                "steer"
              ],
              "description": "start 开始新一轮，steer 补充当前一轮。"
            },
            "delivery_id": {
              "type": "string",
              "description": "可选的投递去重标识。"
            },
            "on_complete": {
              "type": "object",
              "description": "可选结果回传地址，由调用方适配器提供；不影响未配置回传的任务。"
            }
          },
          "required": [
            "session_id",
            "text",
            "mode"
          ],
          "additionalProperties": false
        },
        "completionCallback": {
          "version": 1,
          "parameter": "on_complete"
        }
      }
    }
  }
}
```

## 导出说明

- 当前可见操作：8 个。
- 裁剪前：3131 个字符；未触发 12000 字符裁剪阈值。
- 未显示的操作：`codex_plugin_status`、`create_view`、`release_view`、`codex_plugin_install`。
- 微信帮助会排除原生 Qt 视图操作，以及不在微信操作允许列表中的操作；实际执行时仍须通过平台权限检查。
- 操作说明来自组件 `describe()`，不是直接把 README 或源代码交给模型。
