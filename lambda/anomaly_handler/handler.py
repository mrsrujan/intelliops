"""
Lambda: Kinesis → SageMaker sliding-window anomaly detection.

Trigger: Kinesis Data Stream (intelliops-dev-metrics)
Each invocation receives a batch of records. We maintain a per-service
sliding window of the last 60 data points in DynamoDB, then call the
SageMaker endpoint. If anomaly_score exceeds the threshold we publish
an SNS alert for the RCA handler.
"""

import base64
import json
import os
import boto3
from datetime import datetime, timezone
from decimal import Decimal

SAGEMAKER_ENDPOINT = os.environ["SAGEMAKER_ENDPOINT"]
SNS_TOPIC_ARN      = os.environ["SNS_TOPIC_ARN"]
DYNAMODB_TABLE     = os.environ.get("DYNAMODB_TABLE", "intelliops-metric-windows")
AWS_REGION         = os.environ.get("AWS_REGION", "us-east-1")
WINDOW_SIZE        = 60

sm_runtime = boto3.client("sagemaker-runtime", region_name=AWS_REGION)
dynamodb   = boto3.resource("dynamodb",        region_name=AWS_REGION)
sns        = boto3.client("sns",               region_name=AWS_REGION)
table      = dynamodb.Table(DYNAMODB_TABLE)


def _load_window(service: str) -> list:
    resp = table.get_item(Key={"service": service})
    item = resp.get("Item")
    if not item:
        return []
    return [list(map(float, pt)) for pt in item["window"]]


def _save_window(service: str, window: list):
    table.put_item(Item={
        "service": service,
        "window": [[Decimal(str(v)) for v in pt] for pt in window],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })


def _infer(window: list) -> dict:
    payload = json.dumps({"instances": window})
    resp    = sm_runtime.invoke_endpoint(
        EndpointName=SAGEMAKER_ENDPOINT,
        ContentType="application/json",
        Body=payload,
    )
    return json.loads(resp["Body"].read())


def _alert(service: str, namespace: str, result: dict, record: dict):
    message = {
        "alert_type":    "AnomalyDetected",
        "service":       service,
        "namespace":     namespace,
        "anomaly_score": result["anomaly_score"],
        "threshold":     result["threshold"],
        "metrics":       record,
        "timestamp":     datetime.now(timezone.utc).isoformat(),
    }
    sns.publish(
        TopicArn=SNS_TOPIC_ARN,
        Subject=f"IntelliOps Anomaly: {service}",
        Message=json.dumps(message),
        MessageAttributes={
            "alert_type": {"DataType": "String", "StringValue": "AnomalyDetected"},
            "service":    {"DataType": "String", "StringValue": service},
        },
    )
    print(f"SNS alert published for {service}  score={result['anomaly_score']:.4f}")


def handler(event, context):
    for kinesis_record in event.get("Records", []):
        raw    = base64.b64decode(kinesis_record["kinesis"]["data"])
        record = json.loads(raw)

        service   = record.get("service", "unknown")
        namespace = record.get("namespace", "apps-dev")

        # Build feature vector: [cpu_pct, memory_pct, p95_latency_ms]
        point = [
            record.get("cpu_pct",        0.0),
            record.get("memory_pct",     0.0),
            record.get("p95_latency_ms", 0.0),
        ]

        window = _load_window(service)
        window.append(point)
        if len(window) > WINDOW_SIZE:
            window = window[-WINDOW_SIZE:]
        _save_window(service, window)

        if len(window) < WINDOW_SIZE:
            print(f"{service}: window filling ({len(window)}/{WINDOW_SIZE}) — skipping inference")
            continue

        result = _infer(window)
        print(f"{service}: score={result['anomaly_score']:.4f}  anomaly={result['is_anomaly']}")

        if result["is_anomaly"]:
            _alert(service, namespace, result, record)

    return {"statusCode": 200}
