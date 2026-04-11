# A2UI Tool Visualization Guide (⚡ and ✓ Pills)

This guide documents the "Pill Visualization" pattern used to expose hidden
multi-agent orchestration to the end user in real-time.

## Overview

In complex multi-agent systems, a primary orchestrator (e.g., Marathon Planner)
often calls multiple specialist agents (Traffic, Economic, etc.). Without
visualization, the user sees a long period of silence followed by a bulk
response.

The **Pill Pattern** solves this by emitting real-time status indicators (⚡ for
"Calling" and ✓ for "Received") into the chat bubble as orchestration happens.

## Backend Implementation (`agent_executor.py`)

To visualize a tool call, the backend must intercept the model's `function_call`
and `function_response` events and emit them as A2A `DataPart`s.

### 1. Visualizing the Call (⚡)

When the model emits a `function_call` part, the orchestrator should immediately
yield an SSE event containing a `DataPart` with a `call` key.

```python
if part.function_call:
    # Emit a DataPart representing the call
    yield Response(
        events=[
            TaskArtifactUpdateEvent(
                task_id=task_id,
                artifact=Artifact(
                    artifact_id=f"tool-{part.function_call.name}-{message_id}", # Stable ID
                    append=True,
                    parts=[
                        DataPart(
                            data={
                                "call": {
                                    "name": part.function_call.name,
                                    "args": part.function_call.args
                                }
                            }
                        )
                    ],
                ),
            )
        ]
    )
```

### 2. Visualizing the Response (✓)

When the tool execution completes, yield another `DataPart` with the **same
`artifact_id`** but now containing a `response` key.

```python
if part.function_response:
    yield Response(
        events=[
            TaskArtifactUpdateEvent(
                task_id=task_id,
                artifact=Artifact(
                    artifact_id=f"tool-{part.function_response.name}-{message_id}",
                    append=True, # Append to the existing pill state
                    parts=[
                        DataPart(
                            data={
                                "response": {
                                    "name": part.function_response.name,
                                    "result": part.function_response.response
                                }
                            }
                        )
                    ],
                ),
            )
        ]
    )
```

## Frontend Rendering

The Angular client identifies `DataPart`s containing `call` or `response` keys
and renders them as specialized UI elements:

- **⚡ Call Pill**: Indicates the agent is currently waiting for a
  tool/sub-agent.
- **✓ Response Pill**: Indicates the tool data has been received and integrated.

> [!TIP] Use stable `artifact_id`s (e.g., combining the tool name with a message
> index) to ensure that the "Call" pill is correctly converted into a "Response"
> pill instead of appearing as a new element.

## Best Practices

1. **Progressive Integrity**: Ensure `append: true` is used in SSE events so
   that tool pills appear alongside streaming text.
2. **Stable Mapping**: Map tool names to human-friendly labels in the UI (e.g.,
   `traffic_planner_agent` -> `Traffic Planner`).
3. **Data Filtering**: Do not send massive JSON responses into the `response`
   DataPart; send only summary identifiers or metadata needed for visualization
   to keep the SSE stream light.
