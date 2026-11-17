# Polaris.Ui 1.0

A small Qt Quick control library shared by Polaris-hosted views. It contains visual tokens and native Qt controls, with no component identity, authorization, network calls or service lifecycle.

Configure the existing engine before loading a view:

```python
from polaris_platform.ui import configure_qml_engine
configure_qml_engine(engine)
```

Each view owns its theme instance. Changing one theme does not change another view:

```qml
import QtQuick
import Polaris.Ui 1.0 as Ui

Column {
    Ui.Theme { id: colors; mode: "dark" }
    Ui.Button { theme: colors; text: "Continue"; glyph: "right"; primary: true }
    Ui.TextField { theme: colors; placeholderText: "Name" }
    Ui.ComboBox { theme: colors; model: ["First", "Second"] }
}
```

Every control requires an explicit `theme` object. This property is separate from Qt's native `palette` property. Native properties and signals such as `enabled`, `focusPolicy`, `clicked`, `accepted`, `currentIndex` and `activated` remain available.

| Type | Public appearance properties |
| --- | --- |
| `Theme` | `mode`: `dark`, `light`, or `warm`; readonly colors and size tokens |
| `Icon` | `theme`, `kind`, `ink`, standard `width` / `height` |
| `Button` | `theme`, `glyph`, `primary`, `hint`, `truncateLabel`; native `text` / `enabled` |
| `NavigationItem` | `theme`, `glyph`, `selected`, `compact`, `hint`; native `text` / `enabled` |
| `ScrollBar` | `theme`; native orientation, size, position, policy and pressed state |
| `TextField` | `theme`; native text, selection, input method and editing properties |
| `ComboBox` | `theme`; native model, `textRole`, index, popup and selection properties |

Buttons are text-only by default (`glyph: ""`). Set `glyph: "plus"` explicitly for an add action, or choose another icon. `hint` supplies the accessible name and tooltip for icon-only actions. Navigation entries align content to the left and show a tooltip when compact or truncated. Buttons and navigation preserve Qt keyboard activation and focus semantics. Fields preserve native editing and input-method behavior. Disabled controls cannot activate and use muted visuals.

`ComboBox` accepts plain arrays, object arrays with `textRole`, and standard multi-role `ListModel` models with `textRole`.

Colors are the existing graphite, mist and warm-sand palette: `panel`, `sidebar`, `card`, `ink`, `muted`, `quiet`, `border`, `hover`, `pressed`, `selected`, `selectedInk`, `accent`, `accentInk`, `accentHover`, `softAccent`, `focus`, `scrollThumb`, and `error`.

Size tokens are `fontSizeSmall`, `fontSizeBody`, `fontSizeTitle`, `spaceSmall`, `spaceMedium`, `spaceLarge`, `radiusSmall`, `radiusMedium`, `radiusLarge`, `controlHeight`, `navigationHeight`, and `iconSize`. Layout width remains owned by each view; labels elide within the assigned control width.

The native example at `examples/Controls.qml` demonstrates all seven controls in the three themes. The Canvas is the first production consumer. Its gesture handle, mounting, window timer, storage and background application behavior remain Canvas responsibilities.
