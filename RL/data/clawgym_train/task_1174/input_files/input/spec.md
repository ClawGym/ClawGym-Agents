# Widget Service API Specification

Overview
- Build a production-ready FastAPI skeleton that manages in-memory “widgets”.
- Use an async lifespan context manager to initialize shared state on app.state and clean it up on shutdown.
- Include a yield-based dependency to demonstrate per-request setup/cleanup logic.
- Provide at least one token-protected endpoint with OAuth2PasswordBearer for documentation and custom validation logic.
- Demonstrate BackgroundTasks usage on creation.
- Include a plain-text health endpoint.
- Use Pydantic v2 models and patterns.

Data Model (conceptual)
- Widget:
  - id: UUID (server-generated)
  - name: string (min length 1)
  - quantity: integer (>= 0)
  - tags: list[string] (default empty list)
  - metadata: optional dict[string, any] (default empty dict)
- RenameRequest:
  - new_name: string (min length 1)
- List query params:
  - tag: optional string filter (min length 1)
  - limit: integer 1..50 (default 10)
- Note: Use Pydantic v2 Field(default_factory=...) for mutable fields (e.g., tags, metadata). Use Annotated with Field constraints where appropriate (e.g., min_length, ge/le).

Shared State (lifespan)
- On startup (lifespan enter):
  - Initialize:
    - app.state.widgets: dict[str(uuid) -> widget dict]
    - app.state.name_index: dict[str(name lower) -> uuid] to enforce unique names
    - app.state.logs: list[str] for simple in-memory “log” messages
    - app.state.request_count: int initialized to 0
  - Optionally pre-seed no data.
- On shutdown (lifespan exit):
  - Clear or finalize state (e.g., append a shutdown log entry) and ensure resources are cleaned up.

Dependencies
- Yield-based request context dependency:
  - get_request_context:
    - Before yield: allocate a per-request context (e.g., request_id)
    - After yield: append a message to app.state.logs and increment app.state.request_count
    - Must execute cleanup even when the endpoint raises an exception
- Security dependency:
  - OAuth2PasswordBearer for docs (tokenUrl may be a dummy string like "/auth/token")
  - get_current_user:
    - Accepts token string
    - If token == "secrettoken": return a user object with role="admin"
    - If token starts with "user:": return a user with role="user"
    - Otherwise raise HTTPException(status_code=401, detail="Invalid or missing token")
  - Note: OAuth2PasswordBearer does not validate tokens by itself; implement validation logic in get_current_user.

Endpoints

1) POST /widgets
- Description: Create a new widget.
- Security: Public (no auth).
- Request body: JSON matching Widget creation inputs (name, quantity, tags, metadata).
  - name: required, min length 1, must be unique case-insensitively among existing widgets.
  - quantity: required, int >= 0.
  - tags: optional list[str], default [].
  - metadata: optional dict, default {}.
- Behavior:
  - Generate a UUID for id.
  - Enforce unique name (409 Conflict on duplicate).
  - Schedule a BackgroundTasks job to “index” the widget (e.g., append a log entry).
- Response:
  - On success: 201 Created
  - Return a dict payload (not a Pydantic model) containing at least: id, name, quantity, tags.
- Errors:
  - 409 if name already exists.
  - 422 for validation errors from Pydantic (e.g., empty name, negative quantity).

2) GET /widgets/{widget_id}
- Description: Fetch a single widget by UUID.
- Security: Public.
- Path params: widget_id (UUID).
- Response:
  - 200 with widget dict (id, name, quantity, tags, metadata may be included).
  - 404 if not found.
  - 422 if invalid UUID format (FastAPI handles this).

3) GET /widgets
- Description: List widgets with optional filtering.
- Security: Public.
- Query params:
  - tag: optional string, min_length=1. If provided, only widgets containing this tag are returned.
  - limit: optional int between 1 and 50 inclusive. Default 10.
- Response:
  - 200 with dict { "items": [widget...], "count": <int> }.
- Notes:
  - Use Annotated for limit with Field(ge=1, le=50) and for tag with Field(min_length=1) to demonstrate v2 constraints.

4) POST /widgets/{widget_id}/actions/rename
- Description: Rename an existing widget.
- Security: Requires token (get_current_user).
- Request body: { "new_name": "<string min length 1>" }.
- Behavior:
  - If widget not found: 404.
  - If new_name is already in use (case-insensitive): 409.
  - On success, update the name and name index.
- Response:
  - 200 with dict { "id": "<uuid>", "name": "<new_name>" }.
- Errors:
  - 401 if token invalid or missing.
  - 404 if widget not found.
  - 409 if new_name conflicts.

5) GET /healthz
- Description: Health check returning plain text.
- Security: Public.
- Behavior:
  - Optionally simulate minimal latency using await asyncio.sleep(0.01) (no blocking time.sleep).
- Response:
  - 200 with plain text body "ok".
  - Use Response(media_type="text/plain").

Error Handling
- Use raise HTTPException for expected error paths (401, 404, 409).
- Do not return Response objects for errors to avoid bypassing middleware.

Background Tasks
- Used in POST /widgets to simulate indexing/logging the new widget.
- Add a simple function that appends a message into app.state.logs.
- Document that BackgroundTasks run in the same process after responding and are not guaranteed for long-running work.

Validation and Serialization
- Pydantic v2 only.
- Use Field(default_factory=list) for tags and Field(default_factory=dict) for metadata to avoid shared mutable defaults.
- Use model_dump for serialization within your code paths where needed; return dict payloads from endpoints.

Testing (to be implemented in output/tests/test_app.py)
- Use httpx.AsyncClient with ASGITransport for in-process testing.
- Cover:
  - Successful POST /widgets returns 201 and expected payload.
  - Error path: POST /widgets with duplicate name returns 409 or rename with invalid token returns 401.
  - Optional: GET /healthz returns plain text "ok".
- Ensure tests import the app instance and run fully async.

Non-Functional
- No external services or databases; use in-memory dicts and lists within app.state.
- Avoid time.sleep in async code.

Status Codes Summary
- 201: Widget created
- 200: Successful fetch/list/rename/health
- 401: Invalid or missing token
- 404: Not found
- 409: Name conflict
- 422: Validation errors