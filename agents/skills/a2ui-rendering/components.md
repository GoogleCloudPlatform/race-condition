# A2UI Component Catalog

Reference for the 18 standard A2UI v0.8.0 primitives. Loaded only
when an agent needs to look up component-specific props.

## Layout

| Type    | Required Props                      | Optional Props             | Notes                                                   |
|---------|-------------------------------------|----------------------------|---------------------------------------------------------|
| Column  | `children`                          | `distribution`, `alignment`| Vertical container                                      |
| Row     | `children`                          | `distribution`, `alignment`| Horizontal container                                    |
| List    | `children`                          | `direction`, `alignment`   | Scrollable container                                    |
| Card    | `child`                             | --                         | Single-child wrapper with elevated styling              |
| Tabs    | `tabItems`                          | --                         | Each item: `{"title": wrapped_string, "child": "id"}`   |
| Modal   | `entryPointChild`, `contentChild`   | --                         | Overlay dialog                                          |
| Divider | --                                  | `axis`                     | Default horizontal                                      |

## Display

| Type        | Required Props    | Optional Props               | Notes                                       |
|-------------|-------------------|------------------------------|---------------------------------------------|
| Text        | `text` (wrapped)  | `usageHint`                  | Hints: h1-h5, body, caption, title, label   |
| Image       | `url` (wrapped)   | `fit`, `usageHint`           |                                             |
| Icon        | `name` (wrapped)  | --                           | Material icon names                         |
| Video       | `url` (wrapped)   | `autoplay` (wrapped bool)    |                                             |
| AudioPlayer | `url` (wrapped)   | `description` (wrapped)      |                                             |

## Input

| Type           | Required Props       | Optional Props                    | Notes                                                                         |
|----------------|----------------------|-----------------------------------|-------------------------------------------------------------------------------|
| Button         | `child`, `action`    | `primary`                         | `child` = component ID, `action` = `{"name": "action_name"}`                  |
| TextField      | `label` (wrapped)    | `text`, `textFieldType`           |                                                                               |
| CheckBox       | `label` (wrapped)    | `value`                           |                                                                               |
| Slider         | `value`              | `minValue`, `maxValue`            |                                                                               |
| MultipleChoice | `selections`         | `options`, `maxAllowedSelections` |                                                                               |
| DateTimeInput  | --                   | `value`, `enableDate`, `enableTime`|                                                                              |
