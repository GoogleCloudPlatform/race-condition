# A2UI Rendering — Worked Examples

Three complete `surfaceUpdate` + `beginRendering` pairs covering the
most common patterns. Loaded only when an agent needs to see a full
payload.

## Example 1: Simple Info Card

**Call 1 — surfaceUpdate:**

```json
{
  "surfaceUpdate": {
    "surfaceId": "info",
    "components": [
      {"id": "heading", "component": {"Text": {"text": {"literalString": "Status Report"}, "usageHint": "h2"}}},
      {"id": "body", "component": {"Text": {"text": {"literalString": "All systems operational."}, "usageHint": "body"}}},
      {"id": "content-col", "component": {"Column": {"children": {"explicitList": ["heading", "body"]}}}},
      {"id": "main-card", "component": {"Card": {"child": "content-col"}}}
    ]
  }
}
```

**Call 2 — beginRendering:**

```json
{"beginRendering": {"surfaceId": "info", "root": "main-card"}}
```

## Example 2: Data List Card

**Call 1 — surfaceUpdate:**

```json
{
  "surfaceUpdate": {
    "surfaceId": "sponsors",
    "components": [
      {"id": "title", "component": {"Text": {"text": {"literalString": "Event Sponsors"}, "usageHint": "h3"}}},
      {"id": "divider", "component": {"Divider": {}}},
      {"id": "s1", "component": {"Text": {"text": {"literalString": "Acme Corp"}}}},
      {"id": "s2", "component": {"Text": {"text": {"literalString": "Globex Inc"}}}},
      {"id": "s3", "component": {"Text": {"text": {"literalString": "Initech"}}}},
      {"id": "sponsor-list", "component": {"List": {"children": {"explicitList": ["s1", "s2", "s3"]}}}},
      {"id": "content", "component": {"Column": {"children": {"explicitList": ["title", "divider", "sponsor-list"]}}}},
      {"id": "card", "component": {"Card": {"child": "content"}}}
    ]
  }
}
```

**Call 2 — beginRendering:**

```json
{"beginRendering": {"surfaceId": "sponsors", "root": "card"}}
```

## Example 3: Dashboard with Metrics and Action Button

**Call 1 — surfaceUpdate:**

```json
{
  "surfaceUpdate": {
    "surfaceId": "dashboard",
    "components": [
      {"id": "dash-title", "component": {"Text": {"text": {"literalString": "Marathon Dashboard"}, "usageHint": "h2"}}},
      {"id": "sep1", "component": {"Divider": {}}},
      {"id": "metric1", "component": {"Text": {"text": {"literalString": "Safety Score: 0.92 (Pass)"}}}},
      {"id": "metric2", "component": {"Text": {"text": {"literalString": "Logistics: 0.85 (Pass)"}}}},
      {"id": "metric3", "component": {"Text": {"text": {"literalString": "Budget: 0.78 (Warning)"}}}},
      {"id": "metrics-col", "component": {"Column": {"children": {"explicitList": ["metric1", "metric2", "metric3"]}}}},
      {"id": "sep2", "component": {"Divider": {}}},
      {"id": "btn-label", "component": {"Text": {"text": {"literalString": "Run Simulation"}}}},
      {"id": "run-btn", "component": {"Button": {"child": "btn-label", "action": {"name": "run_simulation"}, "primary": {"literalBoolean": true}}}},
      {"id": "content-col", "component": {"Column": {"children": {"explicitList": ["dash-title", "sep1", "metrics-col", "sep2", "run-btn"]}}}},
      {"id": "dashboard-card", "component": {"Card": {"child": "content-col"}}}
    ]
  }
}
```

**Call 2 — beginRendering:**

```json
{"beginRendering": {"surfaceId": "dashboard", "root": "dashboard-card"}}
```
