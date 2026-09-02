"""
Lambda: SNS anomaly alert → Bedrock Claude RCA → Slack + DynamoDB.

Trigger: SNS topic (intelliops-dev-alerts)
Calls incident_summarizer.py to build context, call Claude, and return RCA.
Posts a rich Slack message with root cause and recommended actions.
"""

import json
import os
import sys
import boto3
from datetime import datetime, timezone

# Allow importing from the shared ai/ layer (bundled into Lambda package)
sys.path.insert(0, "/opt/python")

from incident_summarizer import summarize_incident

SLACK_WEBHOOK   = os.environ.get("SLACK_WEBHOOK_URL", "")
DYNAMODB_TABLE  = os.environ.get("DYNAMODB_TABLE", "intelliops-rca-audit")
AWS_REGION      = os.environ.get("AWS_REGION", "us-east-1")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
table    = dynamodb.Table(DYNAMODB_TABLE)


def _post_slack(result: dict):
    if not SLACK_WEBHOOK:
        return
    import urllib.request
    rca    = result["rca"]
    emoji  = "🔴" if rca.get("escalate") else "🟡"
    conf   = rca.get("confidence", "unknown").upper()
    blocks = {
        "blocks": [
            {"type": "header", "text": {"type": "plain_text",
             "text": f"{emoji} IntelliOps RCA — {result['service']}"}},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*Alert:*\n{result['alert_type']}"},
                {"type": "mrkdwn", "text": f"*Confidence:*\n{conf}"},
                {"type": "mrkdwn", "text": f"*Anomaly Score:*\n{result['anomaly_score']:.4f}"},
                {"type": "mrkdwn", "text": f"*Namespace:*\n{result['namespace']}"},
            ]},
            {"type": "section", "text": {"type": "mrkdwn",
             "text": f"*Root Cause:*\n{rca.get('root_cause', 'N/A')}"}},
            {"type": "section", "text": {"type": "mrkdwn",
             "text": f"*Blast Radius:*\n{rca.get('blast_radius', 'N/A')}"}},
            {"type": "section", "text": {"type": "mrkdwn",
             "text": "*Recommended Actions:*\n" +
                     "\n".join(f"• {a}" for a in rca.get("recommended_actions", []))}},
            {"type": "section", "text": {"type": "mrkdwn",
             "text": f"*Auto-Remediation:*\n{rca.get('auto_remediation', 'None triggered')}"}},
            {"type": "context", "elements": [
                {"type": "mrkdwn", "text": f"🕐 {result['timestamp']}"}
            ]},
        ]
    }
    req = urllib.request.Request(
        SLACK_WEBHOOK,
        data=json.dumps(blocks).encode(),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=5)


def _store_audit(result: dict):
    table.put_item(Item={
        "rca_id":        f"{result['service']}-{result['timestamp']}",
        "timestamp":     result["timestamp"],
        "service":       result["service"],
        "namespace":     result["namespace"],
        "alert_type":    result["alert_type"],
        "anomaly_score": str(result["anomaly_score"]),
        "root_cause":    result["rca"].get("root_cause", ""),
        "escalate":      result["rca"].get("escalate", False),
        "confidence":    result["rca"].get("confidence", ""),
    })


def handler(event, context):
    for record in event.get("Records", []):
        sns_message = json.loads(record["Sns"]["Message"])

        service       = sns_message.get("service",       "unknown")
        namespace     = sns_message.get("namespace",     "apps-dev")
        alert_type    = sns_message.get("alert_type",    "AnomalyDetected")
        anomaly_score = float(sns_message.get("anomaly_score", 0.0))

        print(f"Processing RCA for {service}  alert={alert_type}  score={anomaly_score:.4f}")

        result = summarize_incident(
            service=service,
            namespace=namespace,
            alert_type=alert_type,
            anomaly_score=anomaly_score,
        )

        _store_audit(result)
        _post_slack(result)

        print(f"RCA complete: {json.dumps(result['rca'], indent=2)}")

    return {"statusCode": 200}
