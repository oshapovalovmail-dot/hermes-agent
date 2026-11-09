"""Real, scoped HTTP checks; accepted writes never count as derived memory."""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from stack_paths import provider_names, read_key
from stack_sources import PINS


def request(base: str, path: str, body: dict | None = None, *, headers: dict | None = None,
            timeout: float = 20) -> dict:
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port:
        raise ValueError("backend checks require explicit loopback endpoints from owned state")
    payload = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=payload,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        # Backend errors may contain model/provider internals; do not echo their bodies.
        raise RuntimeError(f"backend HTTP {error.code} on {path.split('?')[0]}") from None


def dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def check_frida(base: str) -> dict:
    metadata = request(base, "/health")
    expected = {"model_loaded": True, "dimensions": 1536,
                "embedding_contract": PINS["embedding_contract"], "max_input_tokens": 512,
                "input_prefix": "search_document: ", "truncation": "reject"}
    if any(metadata.get(name) != value for name, value in expected.items()):
        raise RuntimeError("FRIDA effective contract/readiness differs from pinned contract")
    texts = ["Database backup restoration PostgreSQL", "Restoring a PostgreSQL database backup",
             "Chocolate cake recipe with vanilla icing"]
    response = request(base, "/v1/embeddings", {"model": "frida", "input": texts})
    vectors = [entry["embedding"] for entry in response["data"]]
    if len(vectors) != len(texts) or any(len(vector) != 1536 for vector in vectors):
        raise RuntimeError("FRIDA response shape differs from contract")
    norms = [math.sqrt(dot(vector, vector)) for vector in vectors]
    if any(not math.isfinite(value) or abs(value - 1) > 1e-4 for value in norms):
        raise RuntimeError("FRIDA returned non-finite or unnormalized vectors")
    related, unrelated = dot(vectors[0], vectors[1]), dot(vectors[0], vectors[2])
    if related <= unrelated:
        raise RuntimeError("FRIDA semantic negative control failed")
    return {"passed": True, "contract": metadata["embedding_contract"],
            "norms": norms, "related_similarity": related, "unrelated_similarity": unrelated}


def items(response: dict) -> list:
    value = response.get("items", response.get("data", []))
    return value if isinstance(value, list) else []


def semantic_match(value, canary: str, *, scoped_subject: bool = False) -> bool:
    # Search/request metadata is not derived evidence.
    def texts(item):
        if isinstance(item, str):
            return [item]
        if isinstance(item, list):
            return [text for row in item for text in texts(row)]
        if isinstance(item, dict):
            return [text for key in ("content", "text", "conclusion") for text in texts(item.get(key))]
        return []
    bodies = [re.sub(r", as stated by synthetic-user(?=[.!?]|$)", "", text.casefold())
              for text in texts(value)]
    # Conservative English canary grammar, not a general semantic judge. Fail closed
    # on polarity conflicts and never join separate subjects/documents into proof.
    denied = r"\b(?:not|never|false|no longer|revok\w*|retract\w*|withdraw\w*)\b"
    if any(re.search(denied, body) for body in bodies):
        return False
    subject = r"(?:the project |project )?" + re.escape(canary.casefold())
    preference = subject + r" (?:permanently )?(?:prefers|has chosen) ([^.!?\n]+)"
    if any(match.group(1).strip() != "cobalt blue"
           for body in bodies for match in re.finditer(preference, body)):
        return False
    reported = r"(?:(?:on [a-z]+ \d{1,2}, \d{4}, )?synthetic-user state[sd] that )?"
    predicate = r" (?:permanently )?(?:prefers|has chosen) cobalt blue[.!]?"
    patterns = [reported + subject + predicate]
    sentences = [sentence.strip("-* \t") for body in bodies for sentence in re.split(r"(?<=[.!?])\s+|\n+", body)]
    lasting = r"(?:lasting|permanent|long-term) project preference"
    suffix = r"(?: as (?:the project's color|a " + lasting + r"))?(?:; this is a " + lasting + r")?"
    # A scoped positive never overrides a conflicting read, including implicit choices.
    if any(not re.fullmatch("cobalt blue" + suffix, match.group(1))
           for sentence in sentences
           if (match := re.fullmatch(r"(?:permanently )?(?:prefers|has chosen) ([^.!?\n]+)[.!]?", sentence))):
        return False
    if scoped_subject:
        # Only the causal entity-diff verifier may supply an implicit subject.
        patterns.append(r"(?:permanently )?prefers cobalt blue" + suffix + r"[.!]?")
    return any(re.fullmatch(pattern, sentence) for sentence in sentences for pattern in patterns)


def check_honcho(base: str, *, storage_only: bool, timeout: float) -> dict:
    identity = "probe-" + uuid.uuid4().hex
    peer = "synthetic-user"
    text = f"Project {identity} permanently prefers cobalt blue. This is my lasting project preference."
    request(base, "/v3/workspaces", {"id": identity, "metadata": {"memory_stack_probe": True}})
    scope = "/v3/workspaces/" + identity
    request(base, scope + "/peers", {"id": peer})
    request(base, scope + "/sessions", {"id": identity, "peers": {peer: {"observe_me": True}}})
    path = scope + "/sessions/" + identity
    request(base, path + "/messages", {"messages": [{"peer_id": peer, "content": text}]})
    stored = items(request(base, path + "/messages/list", {}))
    if not any(row.get("content") == text for row in stored):
        raise RuntimeError("Honcho accepted a write but independent readback did not match")
    result = {"passed": True, "workspace": identity, "session_id": identity,
              "storage": "readback_matched", "derivation": "not_checked"}
    if storage_only:
        return result
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        conclusions = items(request(base, scope + "/conclusions/list", {}))
        queue = request(base, scope + "/queue/status?session_id=" + identity)
        complete = (queue.get("completed_work_units", 0) > 0
                    and queue.get("pending_work_units") == 0 and queue.get("in_progress_work_units") == 0)
        if conclusions and complete:
            found = request(base, scope + "/conclusions/query", {"query": "cobalt blue project " + identity, "top_k": 10,
                                               "filters": {"observer": peer, "observed": peer, "session_id": identity}})
            candidates = found if isinstance(found, list) else items(found)
            if semantic_match(conclusions, identity) and semantic_match(candidates, identity):
                result.update(derivation="observed_from_message_ingestion", conclusions=len(conclusions),
                              semantic_results=len(candidates), queue_drained=True)
                return result
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    result.update(passed=False, derivation="not_observed", error="LLM derivation/semantic retrieval did not complete before deadline")
    return result


def result_object(response: dict):
    if response.get("status") == "error":
        raise RuntimeError("backend returned a logical error")
    return response.get("result", response)


def memory_rows(value) -> list[dict]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict) and isinstance(row.get("uri"), str)]
    if isinstance(value, dict):
        return [row for key in ["memories", "results", "items"] for row in memory_rows(value.get(key, []))]
    return []


def scoped_memory_match(call, status: dict, identity: str, session: str, documents: dict[str, str]) -> bool:
    result = status.get("result", {})
    archive = result.get("archive_uri", "")
    prefix = f"viking://user/{identity}/sessions/{session}/history/"
    if (status.get("resource_id") != session or result.get("session_id") != session
            or not archive.startswith(prefix) or not re.fullmatch(r"archive_\d+", archive[len(prefix):])
            or result.get("memory_diff_uri") != archive + "/memory_diff.json"):
        return False
    diff = result_object(call("/api/v1/content/read?uri=" + urllib.parse.quote(result["memory_diff_uri"], safe="")))
    diff = json.loads(diff) if isinstance(diff, str) else diff
    if not isinstance(diff, dict) or diff.get("archive_uri") != archive:
        return False
    operations = diff.get("operations", {})
    if operations.get("updates") or operations.get("deletes"):
        return False
    bound = []
    entity_prefix = f"viking://user/{identity}/memories/preferences/{identity}/"
    for entry in operations.get("adds", []):
        if entry.get("memory_type") != "preferences":
            continue
        uri = entry.get("uri", "")
        leaf = uri[len(entity_prefix):]
        if (not uri.startswith(entity_prefix) or not leaf.endswith(".md") or "/" in leaf or leaf.startswith(".")
                or not entry.get("after") or documents.get(uri) != entry["after"]):
            return False
        bound.append(documents[uri])
    return (bool(bound) and semantic_match(bound, identity, scoped_subject=True)
            and semantic_match(list(documents.values()), identity, scoped_subject=True))


def check_openviking(base: str, *, storage_only: bool, timeout: float, api_key: str = "") -> dict:
    identity = "probe-" + uuid.uuid4().hex
    headers = {"X-OpenViking-Account": "default", "X-OpenViking-User": identity,
               "X-OpenViking-Actor-Peer": identity}
    if api_key:
        headers["X-API-Key"] = api_key
    def call(path, body=None):
        return request(base, path, body, headers=headers)
    created = result_object(call("/api/v1/sessions", {"session_id": identity}))
    session = created.get("session_id", identity)
    path = "/api/v1/sessions/" + session
    text = f"Project {identity} permanently prefers cobalt blue. This is my lasting project preference."
    call(path + "/messages", {"role": "user", "content": text, "peer_id": identity})
    stored = result_object(call(path + "/context"))
    def message_text(row):
        if isinstance(row.get("content"), str):
            return row["content"]
        return "".join(part["text"] for part in row.get("parts", [])
                       if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str))
    if not any(isinstance(row, dict) and row.get("role") == "user" and message_text(row) == text
               for row in stored.get("messages", [])):
        raise RuntimeError("OpenViking accepted a write but independent session readback did not match")
    result = {"passed": True, "user": identity, "session_id": session,
              "storage": "readback_matched", "derivation": "not_checked"}
    if storage_only:
        return result
    committed = result_object(call(path + "/commit", {"keep_recent_count": 0}))
    task = committed.get("task_id")
    if not task:
        result.update(passed=False, derivation="unproven", error="commit returned no causal task identifier")
        return result
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = result_object(call("/api/v1/tasks/" + urllib.parse.quote(task, safe="")))
        if status.get("status") in {"failed", "cancelled"}:
            result.update(passed=False, derivation="failed", task_id=task, error="commit task failed; inspect owned backend logs")
            return result
        if status.get("status") == "completed" and status.get("error") is None:
            found = result_object(call("/api/v1/search/find", {"query": "cobalt blue project " + identity,
                                                               "target_uri": "viking://user/memories", "limit": 10}))
            rows = memory_rows(found)
            documents = {}
            uris = []
            for row in rows:
                uri = row["uri"]
                if not uri.startswith("viking://user/") or "/memories/" not in uri:
                    continue
                content = result_object(call("/api/v1/content/read?uri=" + urllib.parse.quote(uri, safe="")))
                if isinstance(content, dict):
                    content = content.get("content", content.get("text", ""))
                if isinstance(content, str):
                    if uri in documents and documents[uri] != content:
                        result.update(passed=False, derivation="inconsistent_read", task_id=task,
                                      error="inconsistent-memory-content")
                        return result
                    documents[uri] = content
                    uris.append(uri)
            if (semantic_match(list(documents.values()), identity)
                    or scoped_memory_match(call, status, identity, session, documents)):
                result.update(derivation="completed_task_and_semantic_readback", task_id=task, memory_uris=uris)
                return result
            result.update(passed=False, derivation="no_derived_memory", task_id=task,
                          error="completed commit did not produce semantically retrievable memory")
            return result
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    result.update(passed=False, derivation="not_completed", task_id=task, error="commit task deadline exceeded")
    return result


def check(state: dict, *, storage_only: bool, timeout: float) -> dict:
    report = {"level": "storage_only" if storage_only else "derived_memory", "checks": {}}
    base = lambda name: "http://127.0.0.1:" + str(state["ports"][name])
    checks = [("frida", lambda: check_frida(base("frida")))]
    for name in provider_names(state["provider"]):
        callback = check_honcho if name == "honcho" else check_openviking
        options = {"storage_only": storage_only, "timeout": timeout}
        if name == "openviking":
            options["api_key"] = read_key(Path(state["root"]) / "openviking.key")
        checks.append((name, lambda callback=callback, name=name, options=options: callback(base(name), **options)))
    for name, callback in checks:
        try:
            report["checks"][name] = callback()
        except (ValueError, RuntimeError, OSError, KeyError) as error:
            report["checks"][name] = {"passed": False, "error": str(error)}
    report["ok"] = all(value.get("passed") is True for value in report["checks"].values())
    report["derivation_verified"] = report["ok"] and not storage_only
    return report
