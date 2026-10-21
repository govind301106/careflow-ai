"""Optional AI pipeline adapter. No service is assumed unless configured.

Contract to negotiate with the pipeline owner is documented in README.md.
"""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class PipelineUnavailable(Exception):
    pass


def submit_case(payload, idempotency_key):
    endpoint = os.getenv("AI_PIPELINE_URL", "").strip()
    if not endpoint:
        raise PipelineUnavailable("AI pipeline is not configured")
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json", "Idempotency-Key": idempotency_key}
    token = os.getenv("AI_PIPELINE_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=float(os.getenv("AI_PIPELINE_TIMEOUT", "8"))) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise PipelineUnavailable("AI pipeline request failed") from exc
    required = {"schema_version", "status", "structured_output", "evidence", "uncertainty_flags"}
    if not isinstance(result, dict) or not required.issubset(result):
        raise PipelineUnavailable("AI pipeline response did not match the agreed schema")
    if result["status"] not in {"PENDING", "COMPLETED", "FAILED"}:
        raise PipelineUnavailable("AI pipeline returned an unsupported status")
    return result
