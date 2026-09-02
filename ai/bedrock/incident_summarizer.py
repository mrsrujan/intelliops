"""
Full RCA pipeline:
  1. Pull Prometheus metric snapshot
  2. Pull CloudWatch logs (last 30 min)
  3. Pull ArgoCD recent deploy history
  4. Build prompt via rca_prompt.py
  5. Call Amazon Bedrock (Claude 3.5 Sonnet)
  6. Return structured RCA result
"""

import json
import os
import boto3
import requests
from datetime import datetime, timedelta, timezone

from rca_prompt import IncidentContext, build_prompt, SYSTEM_PROMPT

BEDROCK_MODEL   = os.environ.get("BEDROCK_MODEL", "anthropic.claude-3-5-sonnet-20241022-v2:0")
PROMETHEUS_URL  = os.environ.get("PROMETHEUS_URL", "http://kube-prometheus-stack-prometheus.monitoring.svc:9090")
ARGOCD_SERVER   = os.environ.get("ARGOCD_SERVER", "")
ARGOCD_TOKEN    = os.environ.get("ARGOCD_TOKEN", "")
AWS_REGION      = os.environ.get("AWS_REGION", "us-east-1")
LOG_GROUP       = os.environ.get("LOG_GROUP", "/intelliops/dev")

bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
cw_logs = boto3.client("logs", region_name=AWS_REGION)


# ── Prometheus helpers ────────────────────────────────────────────────────────

def _prom_scalar(query: str) -> float:
    try:
        resp = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": query},
            timeout=5,
        )
        result = resp.json()["data"]["result"]
        return float(result[0]["value"][1]) if result else 0.0
    except Exception:
        return 0.0


def get_metrics(service: str, namespace: str) -> dict:
    label = f'job="{service}",namespace="{namespace}"'
    return {
        "cpu_pct":        _prom_scalar(
            f'sum(rate(container_cpu_usage_seconds_total{{namespace="{namespace}"}}[5m])) '
            f'/ sum(kube_pod_container_resource_limits{{namespace="{namespace}",resource="cpu"}}) * 100'
        ),
        "memory_pct":     _prom_scalar(
            f'sum(container_memory_working_set_bytes{{namespace="{namespace}"}}) '
            f'/ sum(kube_pod_container_resource_limits{{namespace="{namespace}",resource="memory"}}) * 100'
        ),
        "error_rate_pct": _prom_scalar(
            f'sum(rate(http_requests_total{{{label},status=~"5.."}}[5m])) '
            f'/ sum(rate(http_requests_total{{{label}}}[5m])) * 100'
        ),
        "p95_latency_ms": _prom_scalar(
            f'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{{{label}}}[5m])) by (le)) * 1000'
        ),
    }


# ── CloudWatch Logs ───────────────────────────────────────────────────────────

def get_recent_logs(namespace: str, minutes: int = 30) -> str:
    end   = datetime.now(timezone.utc)
    start = end - timedelta(minutes=minutes)
    try:
        resp = cw_logs.filter_log_events(
            logGroupName=f"{LOG_GROUP}/{namespace}",
            startTime=int(start.timestamp() * 1000),
            endTime=int(end.timestamp() * 1000),
            limit=200,
        )
        lines = [e["message"] for e in resp.get("events", [])]
        return "\n".join(lines)
    except Exception as e:
        return f"Could not fetch logs: {e}"


# ── ArgoCD deploy history ─────────────────────────────────────────────────────

def get_recent_deploys(app_name: str) -> str:
    if not ARGOCD_SERVER or not ARGOCD_TOKEN:
        return "ArgoCD not configured."
    try:
        resp = requests.get(
            f"https://{ARGOCD_SERVER}/api/v1/applications/{app_name}",
            headers={"Authorization": f"Bearer {ARGOCD_TOKEN}"},
            verify=False,
            timeout=5,
        )
        history = resp.json().get("status", {}).get("history", [])[-3:]
        lines = [
            f"  [{h.get('deployedAt', '')}] revision={h.get('revision', '')[:7]} "
            f"source={h.get('source', {}).get('repoURL', '')}"
            for h in history
        ]
        return "\n".join(lines) or "No history available."
    except Exception as e:
        return f"Could not fetch ArgoCD history: {e}"


# ── Bedrock call ──────────────────────────────────────────────────────────────

def call_claude(user_prompt: str) -> dict:
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
    })
    resp   = bedrock.invoke_model(modelId=BEDROCK_MODEL, body=body)
    output = json.loads(resp["body"].read())
    text   = output["content"][0]["text"]
    return json.loads(text)


# ── Public API ────────────────────────────────────────────────────────────────

def summarize_incident(
    service: str,
    namespace: str,
    alert_type: str,
    anomaly_score: float,
) -> dict:
    metrics  = get_metrics(service, namespace)
    logs     = get_recent_logs(namespace)
    deploys  = get_recent_deploys(service)

    ctx = IncidentContext(
        service=service,
        namespace=namespace,
        anomaly_score=anomaly_score,
        alert_type=alert_type,
        cpu_pct=metrics["cpu_pct"],
        memory_pct=metrics["memory_pct"],
        error_rate_pct=metrics["error_rate_pct"],
        p95_latency_ms=metrics["p95_latency_ms"],
        recent_logs=logs,
        recent_deploys=deploys,
    )

    prompt = build_prompt(ctx)
    rca    = call_claude(prompt)

    return {
        "service":      service,
        "namespace":    namespace,
        "alert_type":   alert_type,
        "anomaly_score": anomaly_score,
        "metrics":      metrics,
        "rca":          rca,
        "timestamp":    datetime.now(timezone.utc).isoformat(),
    }
