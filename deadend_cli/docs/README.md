# API docs

## OpenAPI spec

- **openapi.json** / **openapi.yaml** – Full OpenAPI 3.1 spec for the Deadend HTTP API (agents, tasks, health, init, events, LLM).

### Regenerate the spec

From the `deadend_cli` package directory:

```bash
uv run deadend-openapi
```

Output is written to `docs/` by default. Override with:

```bash
OPENAPI_OUTPUT_DIR=/path/to/dir uv run deadend-openapi
```

### Live spec when the server is running

- **JSON:** `GET http://localhost:8000/openapi.json`
- **Swagger UI:** `GET http://localhost:8000/docs`
- **ReDoc:** `GET http://localhost:8000/redoc`
