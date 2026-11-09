"""Scoped Compose/profile configuration, without credentials in Compose or images."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import hashlib
import shutil

from stack_paths import private_write, provider_names, read_key
from stack_sources import PINS
from ov_exact import EXACT_INPUT_SENTINEL

ENTRYPOINT = '''import json, os, pathlib, sys, tempfile
key = pathlib.Path("/run/stack/llm.key").read_text().strip()
os.environ["LLM_OPENAI_API_KEY"] = key
kind = sys.argv[1]
if kind == "openviking":
    config = json.loads(pathlib.Path("/run/stack/ov-template.json").read_text())
    config["vlm"]["api_key"] = key
    config["server"]["root_api_key"] = pathlib.Path("/run/stack/openviking.key").read_text().strip()
    descriptor, name = tempfile.mkstemp(prefix="memory-stack-", suffix=".conf")
    path = pathlib.Path(name)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(config, stream)
    os.execv(sys.executable, [sys.executable, "/opt/stack/ov_bootstrap.py", "--config", str(path), "--host", "0.0.0.0", "--port", "1933"])
commands = {
    "api": ["fastapi", "run", "--host", "0.0.0.0", "--port", "8000", "src/main.py"],
    "deriver": ["python", "-m", "src.deriver"],
    "migrate": ["alembic", "upgrade", "head"],
}
password = pathlib.Path("/run/stack/postgres.key").read_text().strip()
os.environ["DB_CONNECTION_URI"] = "postgresql+psycopg://memory:" + password + "@postgres:5432/memory"
command = commands[kind]
os.execvp(command[0], command)
'''


def model_spec(base: str, model: str) -> dict:
    return {"model": model, "transport": "openai", "structured_output_mode": "json_object", "overrides": {
        "base_url": base, "api_key_env": "LLM_OPENAI_API_KEY"}}


def honcho_environment(base: str, model: str, password: str) -> dict:
    spec = model_spec(base, model)
    embedding = {"model": "ai-forever/FRIDA", "transport": "openai",
                 "dimensions_mode": "never", "max_batch_size": 8,
                 "overrides": {"base_url": "http://frida:8001/v1", "api_key": "local"}}
    return {

        "AUTH_USE_AUTH": "false", "CACHE_ENABLED": "true", "CACHE_URL": "redis://redis:6379/0",
        "LANGFUSE_ENABLED": "false", "TELEMETRY_ENABLED": "false", "HOME": "/tmp",  # no-tmp: ok — scratch inside the isolated Linux container, not the host
        "TIKTOKEN_CACHE_DIR": "/app/token-cache", "LLM_OPENAI_BASE_URL": base,
        "DERIVER_MODEL_CONFIG": json.dumps(spec), "SUMMARY_MODEL_CONFIG": json.dumps(spec),
        "DREAM_DEDUCTION_MODEL_CONFIG": json.dumps(spec), "DREAM_INDUCTION_MODEL_CONFIG": json.dumps(spec),
        "DIALECTIC_LEVELS": json.dumps({level: {"model_config": spec} for level in
                                       ["minimal", "low", "medium", "high", "max"]}),
        "EMBEDDING_MODEL_CONFIG": json.dumps(embedding), "EMBEDDING_VECTOR_DIMENSIONS": "1536",
        "VECTOR_STORE_DIMENSIONS": "1536", "VECTOR_STORE_TYPE": "pgvector",
        "EMBEDDING_MAX_INPUT_TOKENS": "512", "EMBEDDING_TOKENIZER_PATH": "/model/tokenizer.json",
        "EMBEDDING_INPUT_PREFIX": "search_document: ", "EMBEDDING_CHUNK_OVERLAP_RATIO": "0.2",
        "EMBEDDING_MAX_CONCURRENT_EMBEDDINGS": "1", "EMBEDDING_MAX_PENDING_EMBED_TASKS": "4",
        "DERIVER_WORKERS": "1", "DERIVER_FLUSH_ENABLED": "true", "PYTHONDONTWRITEBYTECODE": "1",
    }


def ov_configuration(root: Path, identity: str, base: str, model: str) -> dict:
    return {"default_account": "default", "default_user": identity,
            "server": {"auth_mode": "trusted", "root_api_key": ""},
            "storage": {"workspace": "/data"},
            "embedding": {"dense": {"provider": "openai", "model": "frida",
                                      "api_base": "http://frida:8001/v1", "api_key": "local",
                                      "dimension": 1536, "batch_size": 1, "encoding_format": "float"},
                          "max_concurrent": 1, "max_retries": 0, "max_input_tokens": EXACT_INPUT_SENTINEL},
            "vlm": {"provider": "openai", "api_base": base, "model": model,
                    "api_key": "", "max_retries": 0, "max_concurrent": 1, "timeout": 60},
            "enable_watch_scheduler": False, "default_search_mode": "fast"}


def volume(source: Path, target: str, readonly: bool = False) -> dict:
    return {"type": "bind", "source": str(source), "target": target, "read_only": readonly}


def health(url: str, expression: str = "True") -> dict:
    statement = ("import json,urllib.request;d=json.load(urllib.request.urlopen("
                 + repr(url) + ",timeout=10));assert " + expression)
    return {"test": ["CMD", "python", "-c", statement], "interval": "5s",
            "timeout": "15s", "retries": 30, "start_period": "10s"}


def compose_config(root: Path, state: dict, base: str, model: str, password: str) -> dict:
    names = provider_names(state["provider"])
    ports = state["ports"]
    model_directory = root / "model"
    user = f"{os.getuid()}:{os.getgid()}"
    services = {"frida": {
        "build": {"context": str(root / "build/frida")},
        "command": ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"],
        "ports": [f"127.0.0.1:{ports['frida']}:8001"],
        "volumes": [volume(model_directory, "/opt/frida", True)],
        "environment": {"OMP_NUM_THREADS": "2", "TOKENIZERS_PARALLELISM": "false"},
        "healthcheck": health("http://127.0.0.1:8001/health", "d.get('model_loaded') is True"),
    }}
    if "honcho" in names:
        services["postgres"] = {
            "image": PINS["images"]["postgres"],
            "environment": {"POSTGRES_USER": "memory", "POSTGRES_DB": "memory",
                            "POSTGRES_PASSWORD_FILE": "/run/stack/postgres.key"},
            "volumes": [volume(root / "data/postgres", "/var/lib/postgresql/data"),
                        volume(root / "postgres.key", "/run/stack/postgres.key", True),
                        volume(root / "build/honcho/database/init.sql", "/docker-entrypoint-initdb.d/00-vector.sql", True)],
            "healthcheck": {"test": ["CMD-SHELL", "pg_isready -U memory -d memory"],
                            "interval": "3s", "timeout": "5s", "retries": 30},
        }
        services["redis"] = {"image": PINS["images"]["redis"],
                             "command": ["redis-server", "--appendonly", "yes"],
                             "volumes": [volume(root / "data/redis", "/data")],
                             "healthcheck": {"test": ["CMD", "redis-cli", "ping"],
                                             "interval": "3s", "timeout": "5s", "retries": 30}}
        for name, kind in [("honcho-migrate", "migrate"), ("honcho-api", "api"), ("honcho-deriver", "deriver")]:
            service = {"build": {"context": str(root / "build/honcho")}, "user": user,
                       "command": ["python", "/opt/stack/secret_entry.py", kind],
                       "environment": honcho_environment(base, model, password),
                       "volumes": [volume(root / "llm.key", "/run/stack/llm.key", True),
                                   volume(root / "postgres.key", "/run/stack/postgres.key", True),
                                   volume(model_directory / "tokenizer.json", "/model/tokenizer.json", True)],
                       "depends_on": {"postgres": {"condition": "service_healthy"},
                                      "redis": {"condition": "service_healthy"},
                                      "frida": {"condition": "service_healthy"}}}
            if kind != "migrate":
                service["depends_on"]["honcho-migrate"] = {"condition": "service_completed_successfully"}
            if kind == "api":
                service["ports"] = [f"127.0.0.1:{ports['honcho']}:8000"]
                service["healthcheck"] = health("http://127.0.0.1:8000/health")
            services[name] = service
    if "openviking" in names:
        services["openviking"] = {
            "build": {"context": str(root / "build/openviking")}, "user": user,
            "command": ["python", "/opt/stack/secret_entry.py", "openviking"],
            "ports": [f"127.0.0.1:{ports['openviking']}:1933"],
            "environment": {"HOME": "/tmp", "OV_FRIDA_TOKENIZER_FILE": "/model/tokenizer.json",  # no-tmp: ok — scratch inside the isolated Linux container, not the host
                            "OV_FRIDA_TOKENIZER_SHA256": PINS["assets"]["tokenizer.json"]["sha256"]},
            "volumes": [volume(root / "llm.key", "/run/stack/llm.key", True),
                        volume(root / "openviking.key", "/run/stack/openviking.key", True),
                        volume(model_directory / "tokenizer.json", "/model/tokenizer.json", True),
                        volume(root / "ov-template.json", "/run/stack/ov-template.json", True),
                        volume(root / "data/openviking", "/data")],
            "depends_on": {"frida": {"condition": "service_healthy"}},
            "healthcheck": health("http://127.0.0.1:1933/health"),
        }
    return {"name": state["project"], "services": services}


def profile(root: Path, state: dict) -> None:
    home = root / "hermes-home"
    home.mkdir(mode=0o700, exist_ok=True)
    names = provider_names(state["provider"])
    identity = state["project"]
    config = {"memory": {"provider": names[0], "providers": names},
              "plugins": {"entries": {name: {"enabled": True} for name in names}}}
    if "openviking" in names:
        config["memory"]["openviking"] = {"deployment": "external-compose", "use_ovcli_config": True,
                                          "ovcli_config_path": str(home / "ovcli.conf")}
    private_write(home / "config.yaml", json.dumps(config, indent=2) + "\n")
    if "honcho" in names:
        honcho = {"baseUrl": f"http://127.0.0.1:{state['ports']['honcho']}",
                  "hosts": {"hermes": {"enabled": True, "workspace": identity,
                                        "peerName": "user-" + identity, "aiPeer": "agent-" + identity,
                                        "pinUserPeer": True, "sessionStrategy": "per-session",
                                        "sessionAiPeerPrefix": True, "saveMessages": True,
                                        "writeFrequency": "turn", "recallMode": "hybrid"}}}
        private_write(home / "honcho.json", json.dumps(honcho, indent=2) + "\n")
    if "openviking" in names:
        key_file = root / "openviking.key"
        if not key_file.exists():
            private_write(key_file, secrets.token_urlsafe(32) + "\n")
        connection = {"url": f"http://127.0.0.1:{state['ports']['openviking']}",
                      "api_key": read_key(key_file), "root_api_key": read_key(key_file),
                      "account": "default", "user": identity, "actor_peer_id": identity}
        private_write(home / "ovcli.conf", json.dumps(connection, indent=2) + "\n")
        private_write(home / ".env", "OPENVIKING_CLI_CONFIG_FILE=" + str(home / "ovcli.conf") + "\n"
                      + "OPENVIKING_ACCOUNT=default\nOPENVIKING_USER=" + identity + "\n"
                      + "OPENVIKING_AGENT=" + identity + "\n")


def render(root: Path, state: dict, base: str, model: str, key: str) -> dict:
    private_write(root / "llm.key", key + "\n")
    password = secrets.token_urlsafe(32)
    if "honcho" in provider_names(state["provider"]):
        private_write(root / "postgres.key", password + "\n")
    data_names = (["postgres", "redis"] if "honcho" in provider_names(state["provider"]) else [])
    if "openviking" in provider_names(state["provider"]):
        data_names.append("openviking")
    for name in data_names:
        (root / "data" / name).mkdir(parents=True, mode=0o700, exist_ok=True)
    frida = root / "build/frida"
    private_write(frida / "Dockerfile", f"FROM {PINS['images']['python_frida']}\n"
                  + "WORKDIR /app\nCOPY requirements-runtime.lock .\n"
                  + "RUN pip install --no-cache-dir -r requirements-runtime.lock\nCOPY server.py .\n")
    if "honcho" in provider_names(state["provider"]):
        directory = root / "build/honcho"
        dockerfile = (directory / "Dockerfile").read_text().replace(
            "FROM python:3.13-slim-bookworm", "FROM " + PINS["images"]["python_honcho"])
        dockerfile = dockerfile.replace("COPY uv.lock pyproject.toml /app/",
                                       "COPY uv.lock pyproject.toml /app/\nCOPY sdks/python /app/sdks/python\nCOPY honcho-cli /app/honcho-cli")
        dockerfile += ("\nUSER root\nCOPY stack_secret_entry.py /opt/stack/secret_entry.py\n"
                       + "ENV TIKTOKEN_CACHE_DIR=/app/token-cache\n"
                       + "RUN mkdir /app/token-cache && python -c \"import tiktoken;"
                       + "tiktoken.get_encoding('cl100k_base');tiktoken.get_encoding('o200k_base')\""
                       + " && chmod -R a+rX /app /opt/stack\nUSER app\n")
        (directory / "Dockerfile").write_text(dockerfile)
        private_write(directory / "stack_secret_entry.py", ENTRYPOINT)
    if "openviking" in provider_names(state["provider"]):
        directory = root / "build/openviking"
        directory.mkdir()
        private_write(directory / "stack_secret_entry.py", ENTRYPOINT)
        for helper in ("ov_exact.py", "ov_bootstrap.py"):
            shutil.copyfile(Path(__file__).with_name(helper), directory / helper)
        lock = Path(__file__).with_name("openviking-runtime.lock")
        if hashlib.sha256(lock.read_bytes()).hexdigest() != PINS["openviking_lock_sha256"]:
            raise ValueError("OpenViking dependency lock changed")
        shutil.copyfile(lock, directory / "openviking-runtime.lock")
        private_write(directory / "Dockerfile", f"FROM {PINS['images']['python_frida']}\n"
                      + "COPY openviking-runtime.lock /tmp/openviking-runtime.lock\n"  # no-tmp: ok — scratch inside the isolated Linux container, not the host
                      + "RUN pip install --no-cache-dir --require-hashes -r /tmp/openviking-runtime.lock\n"  # no-tmp: ok — scratch inside the isolated Linux container, not the host
                      + "COPY --chmod=0444 stack_secret_entry.py /opt/stack/secret_entry.py\n"
                      + "COPY --chmod=0444 ov_exact.py ov_bootstrap.py /opt/stack/\n"
                      + "RUN chmod -R a+rX /opt/stack\n")
        template = ov_configuration(root, state["project"], base, model)
        private_write(root / "ov-template.json", json.dumps(template, indent=2) + "\n")
    document = compose_config(root, state, base, model, password)
    # Compose treats '$' as interpolation even in JSON; credentials are never embedded here.
    def escape(value):
        if isinstance(value, str):
            return value.replace("$", "$$")
        if isinstance(value, list):
            return [escape(item) for item in value]
        if isinstance(value, dict):
            return {name: escape(item) for name, item in value.items()}
        return value
    private_write(root / "compose.json", json.dumps(escape(document), indent=2) + "\n")
    profile(root, state)
    return document
