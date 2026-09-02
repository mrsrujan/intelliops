"""
Prometheus → Kinesis metric producer.
Runs every 15 seconds, queries Prometheus for key service metrics,
and puts records onto the Kinesis metrics stream.

Deploy as a Kubernetes CronJob or a long-running Deployment.
"""

import json
import os
import time
import uuid
import logging
from datetime import datetime, timezone

import boto3
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PROMETHEUS_URL  = os.environ.get("PROMETHEUS_URL", "http://kube-prometheus-stack-prometheus.monitoring.svc:9090")
KINESIS_STREAM  = os.environ.get("KINESIS_STREAM", "intelliops-dev-metrics")
AWS_REGION      = os.environ.get("AWS_REGION", "us-east-1")
SCRAPE_INTERVAL = int(os.environ.get("SCRAPE_INTERVAL", "15"))

SERVICES = [
    {"name": "payment-service", "namespace": "apps-dev"},
    {"name": "order-service",   "namespace": "apps-dev"},
]

kinesis = boto3.client("kinesis", region_name=AWS_REGION)


def query(expr: str) -> float:
    try:
        resp = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": expr},
            timeout=5,
        )
        result = resp.json()["data"]["result"]
        return float(result[0]["value"][1]) if result else 0.0
    except Exception as e:
        log.warning("Prometheus query failed: %s", e)
        return 0.0


def collect(service: str, namespace: str) -> dict:
    ns_label = f'namespace="{namespace}"'
    svc_label = f'job="{service}",namespace="{namespace}"'
    return {
        "service":      service,
        "namespace":    namespace,
        "timestamp":    datetime.now(timezone.utc).isoformat(),
        "cpu_pct": query(
            f'sum(rate(container_cpu_usage_seconds_total{{{ns_label},container!="",container!="POD"}}[1m]))'
            f' / sum(kube_pod_container_resource_limits{{{ns_label},resource="cpu"}}) * 100'
        ),
        "memory_pct": query(
            f'sum(container_memory_working_set_bytes{{{ns_label},container!="",container!="POD"}})'
            f' / sum(kube_pod_container_resource_limits{{{ns_label},resource="memory"}}) * 100'
        ),
        "request_rate": query(
            f'sum(rate(http_requests_total{{{svc_label}}}[1m]))'
        ),
        "error_rate_pct": query(
            f'sum(rate(http_requests_total{{{svc_label},status=~"5.."}}[1m]))'
            f' / (sum(rate(http_requests_total{{{svc_label}}}[1m])) + 0.001) * 100'
        ),
        "p95_latency_ms": query(
            f'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{{{svc_label}}}[1m])) by (le)) * 1000'
        ),
    }


def put_record(record: dict):
    kinesis.put_record(
        StreamName=KINESIS_STREAM,
        Data=json.dumps(record).encode(),
        PartitionKey=record["service"],
    )
    log.info("→ Kinesis  %s  cpu=%.1f%%  mem=%.1f%%  err=%.2f%%",
             record["service"], record["cpu_pct"], record["memory_pct"], record["error_rate_pct"])


def main():
    log.info("Starting metric producer  stream=%s  interval=%ds", KINESIS_STREAM, SCRAPE_INTERVAL)
    while True:
        for svc in SERVICES:
            try:
                record = collect(svc["name"], svc["namespace"])
                put_record(record)
            except Exception as e:
                log.error("Failed to collect/ship metrics for %s: %s", svc["name"], e)
        time.sleep(SCRAPE_INTERVAL)


if __name__ == "__main__":
    main()
