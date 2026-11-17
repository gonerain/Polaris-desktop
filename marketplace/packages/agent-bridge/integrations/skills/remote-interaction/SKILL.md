---
name: remote-interaction
description: Ask a human a question through Polaris Agent's remote interaction channel when the user requests remote or Weixin control of this Codex session. Preserve the current session and wait for the human answer.
---

# Remote questions

For a task delivered through Polaris Agent when its user is answering through Weixin, use this plugin's `codex/hook.mjs --ask` instead of a native question box. Resolve `codex/hook.mjs` from this SKILL.md's plugin root (the installed SKILL.md path’s `parents[2]`). Read this installed file's absolute location to find the root; do not guess a different plugin installation.

Execute Node.js with arguments `[absolute_hook_path, "--ask"]`, feeding JSON on stdin:

```json
{"question":"Choose the output format","options":["PDF","Word"]}
```

Use the calling process's CODEX_THREAD_ID; never substitute another chat. The helper must be online, the session explicitly marked, and the originating remote delivery must have an interaction callback. The command waits up to 110 seconds and prints `{"answer":"..."}`. Treat that answer as the human's response to this question. On error or timeout, report that the question was not answered; do not select an option yourself or repeatedly resend it.

Keep questions short (up to 1400 characters); allow a free-text answer even with options. Use a separate request for each question. Permissions are handled by the PermissionRequest hook, not by this question command. Never manufacture an approval reply or change permission settings to avoid a request.
