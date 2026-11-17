# Docker Deployment

OpenJarvis provides Docker images for both CPU-only and GPU-accelerated deployments, along with a Docker Compose configuration that bundles the API server with an Ollama inference backend.

## Quick Start

The container binds `0.0.0.0`, so an **API key is required** — the server
refuses to start on a non-loopback address without one. Set it first:

```bash
cd deploy/docker
cp .env.example .env
export OPENJARVIS_API_KEY="$(openssl rand -hex 32)"
```

Then start both the API server and an Ollama backend with Docker Compose:

```bash
docker compose up -d
```

`docker compose` reads `OPENJARVIS_API_KEY` from `.env` (or your shell
environment) and fails fast if it is unset. Clients must then send
`Authorization: Bearer <key>` on `/v1/*` and `/api/*` requests.
Keep this key available in your shell, or save its value in `.env` for later
Compose invocations. The example uses OpenSSL to generate a random key.

This brings up two services:

| Service  | Port  | Description                        |
|----------|-------|------------------------------------|
| `jarvis` | 8000  | OpenJarvis API server              |
| `ollama` | 11434 | Ollama inference engine            |

Verify the server is running:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status": "ok"}
```

## Docker Images

### CPU-Only Image (`Dockerfile`)

The default `Dockerfile` uses a multi-stage build based on `python:3.12-slim` to produce a minimal image.

**Build stages:**

1. **Builder stage** -- installs `uv` and the `openjarvis[server]` package (which includes FastAPI, uvicorn, and all server dependencies) from the project source.
2. **Runtime stage** -- copies only the installed Python packages and application code from the builder, keeping the final image small.

```dockerfile
FROM python:3.12-slim AS builder

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir uv && \
    uv pip install --system ".[server]"

FROM python:3.12-slim

COPY --from=builder /usr/local /usr/local
COPY --from=builder /app /app
WORKDIR /app

EXPOSE 8000

ENTRYPOINT ["jarvis"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
```

Build it manually from the repository root:

```bash
docker build -f deploy/docker/Dockerfile -t openjarvis:latest .
```

Run it standalone:

```bash
docker run -d -e OPENJARVIS_API_KEY -p 127.0.0.1:8000:8000 openjarvis:latest
```

### Running the built image with a host Ollama server

Use the `openjarvis:latest` image built above. Ollama must already be running
on the host with a model installed and listening on an address reachable from
containers. On Linux, its default loopback-only binding is not reachable via
the Docker host gateway; configure its binding using the
[Ollama server instructions](https://docs.ollama.com/faq#how-do-i-configure-ollama-server)
and restrict access to trusted container traffic.

Set an API key and map each container to a different loopback host port:

```bash
export OPENJARVIS_API_KEY="$(openssl rand -hex 32)"

docker run -d --name openjarvis-8001 \
  -e OPENJARVIS_API_KEY \
  -e OLLAMA_HOST=http://host.docker.internal:11434 \
  -p 127.0.0.1:8001:8000 \
  --add-host host.docker.internal:host-gateway \
  openjarvis:latest serve --engine ollama --host 0.0.0.0 --port 8000

docker run -d --name openjarvis-8003 \
  -e OPENJARVIS_API_KEY \
  -e OLLAMA_HOST=http://host.docker.internal:11434 \
  -p 127.0.0.1:8003:8000 \
  --add-host host.docker.internal:host-gateway \
  openjarvis:latest serve --engine ollama --host 0.0.0.0 --port 8000
```

The API is available at `http://localhost:8001` and
`http://localhost:8003`. Keep the API key out of source control; the commands
read it from the shell environment.

### GPU Image (`Dockerfile.gpu`)

The GPU image is built on `nvidia/cuda:12.4.0-runtime-ubuntu22.04` and includes the CUDA 12.4 runtime libraries, enabling GPU-accelerated inference when paired with a GPU-capable engine like vLLM or SGLang.

```dockerfile
FROM nvidia/cuda:12.4.0-runtime-ubuntu22.04 AS builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip python3-venv && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir uv && \
    uv pip install --system ".[server]"

FROM nvidia/cuda:12.4.0-runtime-ubuntu22.04

RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local /usr/local
COPY --from=builder /app /app
WORKDIR /app

EXPOSE 8000

ENTRYPOINT ["jarvis"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
```

Build the GPU image:

```bash
docker build -f Dockerfile.gpu -t openjarvis:gpu .
```

Run with GPU access (requires the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)):

```bash
docker run -d --gpus all -p 8000:8000 openjarvis:gpu
```

!!! note "NVIDIA Container Toolkit required"
    The host machine must have the NVIDIA Container Toolkit installed for `--gpus` to work. See the [NVIDIA installation guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) for setup instructions.

## Docker Compose Configuration

The [Compose file](../../deploy/docker/docker-compose.yml) defines the OpenJarvis
API server and its Ollama backend. Both require a running Docker host.

### Connect a hosted Command Center

Keep the API key in the server's `.env` file and enter it in the Command Center
Settings alongside the backend URL. Set `OPENJARVIS_CORS_ORIGINS` to the exact
HTTPS origin of your Netlify frontend, without a trailing slash. CORS controls
browser access, and the API key authenticates API requests independently of the
Netlify login.

For an HTTPS reverse proxy on the Docker host, set
`OPENJARVIS_BIND_ADDRESS=127.0.0.1` to bind both published ports to loopback.
Forward the HTTPS backend address to port 8000 only. Ollama communicates with
OpenJarvis over the Compose network.

### Launch a workflow from another app

Use the request example in Workspace for the selected saved workflow. To limit
an automation to starting one workflow, generate a separate random key and
record its SHA-256 digest. This command prints a new key on the first line and
its digest on the second line:

```sh
python -c "import hashlib,secrets; k=secrets.token_urlsafe(32); print(k); print(hashlib.sha256(k.encode()).hexdigest())"
```

Set `OPENJARVIS_WORKFLOW_LAUNCH_KEYS` in the backend environment to a JSON
object mapping the saved workflow ID to its digest, then restart the backend:

```dotenv
OPENJARVIS_WORKFLOW_LAUNCH_KEYS='{"<workflow-id>":"<sha256-digest>"}'
```

Store the raw key in the calling app's credential store. Pass it as the Bearer
token for the workflow's `POST .../runs` request with an `Idempotency-Key`
header and `expected_revision` in the JSON body. Scoped launches return the
run ID and status. Check the run in Command Center using your regular login
and backend connection. Remove the digest and restart the backend to revoke
the key.

For n8n, import the [workflow launch example](../../examples/openjarvis/n8n-workflow-launch.json).
Set the HTTP Request URL to the backend URL and saved workflow ID from
**Run this workflow from another app** in Workspace. Create a **Header Auth**
credential with header name `Authorization` and value `Bearer <workflow-launch-key>`.
Select it in the request node and replace the saved revision and event ID
placeholders. Use the same event ID and request body when retrying that event.
Use a fresh event ID for distinct events.

### Give a collaborator read access to the Shared Brain brief

Use the key-generation command above to create a separate random key and its
SHA-256 digest. Keep the backend's owner API key configured. Set
`OPENJARVIS_SHARED_BRAIN_READ_KEY_SHA256` to the new digest and recreate the
backend service so it loads the setting. Store the original key in the
collaborating client's credential store.

Send `GET /v1/shared-brain/brief` with this key as a Bearer token. The response
contains the full saved brief and its revision. Use this only with clients
you authorize to read that brief. A client holding this key cannot edit the
brief or access other protected endpoints. Remove the digest and recreate
the service to revoke access.

A local MCP client can use OpenJarvis's stdio adapter. Configure the MCP
command to run the Python executable from the OpenJarvis environment with
arguments `-m openjarvis.mcp.shared_brain_stdio`. Pass these environment
variables to the MCP process:

- `OPENJARVIS_SHARED_BRAIN_URL` for the backend base URL.
- `OPENJARVIS_SHARED_BRAIN_READ_KEY` for the read key from your credential store.

The adapter exposes only `read_shared_brain_brief`. It accepts HTTPS backend
URLs and loopback HTTP URLs.

### Persistent data

The `openjarvis-data` named volume persists Command Center state, including
workflows, schedules, approvals, and connector indexes. The `ollama-models`
volume persists downloaded models. If upgrading from an older Compose setup,
back up `/home/openjarvis/.openjarvis` from the existing API container before
replacing it. Existing container files do not migrate automatically to the new
volume.

### Service Dependencies

The `jarvis` service declares `depends_on: ollama`, ensuring the Ollama container starts before the API server. Both services use `restart: unless-stopped` to automatically recover from crashes.

## Custom Configuration

### Mounting a Configuration File

To use a custom `config.toml`, mount it into the container at the expected path (`~/.openjarvis/config.toml`, which is `/root/.openjarvis/config.toml` in the container):

```yaml
services:
  jarvis:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    volumes:
      - ./my-config.toml:/root/.openjarvis/config.toml:ro
    environment:
      - OPENJARVIS_ENGINE_DEFAULT=ollama
      - OPENJARVIS_OLLAMA_HOST=http://ollama:11434
    depends_on:
      - ollama
    restart: unless-stopped
```

### Persisting Data

To persist telemetry data, memory databases, and trace records across container restarts, mount the entire OpenJarvis data directory:

```yaml
services:
  jarvis:
    # ... other config ...
    volumes:
      - openjarvis-data:/root/.openjarvis

volumes:
  ollama-models:
  openjarvis-data:
```

This preserves:

- `telemetry.db` -- inference call telemetry records
- `memory.db` -- the default SQLite memory backend
- `traces.db` -- interaction trace records
- `config.toml` -- user configuration

### Using the GPU Image with Compose

To use the GPU Dockerfile in your Compose setup, change the `dockerfile` field and add GPU resource reservations:

```yaml
services:
  jarvis:
    build:
      context: .
      dockerfile: Dockerfile.gpu
    ports:
      - "8000:8000"
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    environment:
      - OPENJARVIS_ENGINE_DEFAULT=ollama
      - OPENJARVIS_OLLAMA_HOST=http://ollama:11434
    depends_on:
      - ollama
    restart: unless-stopped
```

## Health Check

The API server exposes a `GET /health` endpoint that checks whether the underlying inference engine is responsive:

```bash
curl http://localhost:8000/health
```

A healthy response returns HTTP 200:

```json
{"status": "ok"}
```

An unhealthy engine returns HTTP 503:

```json
{"detail": "Engine unhealthy"}
```

You can integrate this into your Docker Compose healthcheck:

```yaml
services:
  jarvis:
    # ... other config ...
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
```

## Building Custom Images

### Adding Extra Dependencies

To include additional engine backends (such as vLLM or ColBERT memory), modify the install command in the Dockerfile:

```dockerfile
RUN pip install --no-cache-dir uv && \
    uv pip install --system ".[server,inference-vllm,memory-colbert]"
```

### Overriding the Default Command

The entrypoint is `jarvis` and the default command is `serve --host 0.0.0.0 --port 8000`. Override the command to change server options:

```bash
docker run -d -p 9000:9000 openjarvis:latest \
  serve --host 0.0.0.0 --port 9000 --engine ollama --model qwen3:8b
```

Or in Docker Compose:

```yaml
services:
  jarvis:
    build: .
    command: ["serve", "--host", "0.0.0.0", "--port", "9000", "--model", "qwen3:8b"]
    ports:
      - "9000:9000"
```

### Available CLI Options for `jarvis serve`

| Option               | Description                                         |
|----------------------|-----------------------------------------------------|
| `--host`             | Bind address (default: from config, typically `0.0.0.0`) |
| `--port`             | Port number (default: from config, typically `8000`)     |
| `-e` / `--engine`    | Engine backend (`ollama`, `vllm`, `llamacpp`, `sglang`)  |
| `-m` / `--model`     | Default model name                                       |
| `-a` / `--agent`     | Agent for non-streaming requests (`simple`, `orchestrator`, `react`, `openhands`) |

## Pulling Models

After starting the Ollama container, you need to pull at least one model before the API server can serve requests:

```bash
docker compose exec ollama ollama pull qwen3:8b
```

Verify models are available through the API:

```bash
curl http://localhost:8000/v1/models
```
