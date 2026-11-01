# A native view owned by its plugin

Load this directory through the desktop manager and start `org.example.counter`. It receives only the ordinary component Client. Its counter state, QML, button handlers and validation are all implemented here.

The `main` descriptor uses the local `qt-quick-item` profile. The canvas invokes the declared `create_view` operation with its empty parent item. The plugin returns an owned handle and a child QQuickItem. `release_view` disposes only that presentation; `get` and `increment` continue to work. Each button calls the plugin's own public `increment` operation with the creating request's captured context, so later revocation applies to an already displayed view.

A user must explicitly grant the request origin the relevant canvas/window operations and this plugin's `create_view`, `release_view`, and `increment`. Invoke `canvas.mount` with:

```json
{"target":"org.example.counter","view":"main"}
```

The canvas handles placement and the presentation lifetime. It does not interpret counter values or register a counter-specific type. This is trusted same-process Python/Qt software; it is not available through the JSON stdio profile. Count state is intentionally in memory and is reset when this component stops.
