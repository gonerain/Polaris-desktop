---
name: mark-current
description: Mark the current Codex chat in Polaris Agent when the user explicitly asks to mark this conversation, optionally with a name.
---
Only invoke for an explicit user request to mark the current chat. Lifecycle reporting runs through hooks and never needs this skill.

Run `node "${PLUGIN_ROOT}/codex/hook.mjs" --mark "NAME"` through the current chat's shell tool. Resolve PLUGIN_ROOT to the installed plugin directory two levels above this SKILL.md if it is not available to the shell; do not guess another plugin path. NAME is optional and must be properly shell-quoted.

The command uses only CODEX_THREAD_ID to identify the current chat. Do not replace a missing value with CODEX_SESSION_ID, cwd, a recently active chat, a history search, or a model-supplied session ID. A missing identity or disconnected bridge is an error; report that marking did not complete. Success requires a helper response with `result` and no `error`. Do not announce success based on exit status alone.
