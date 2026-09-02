"""
Builds the structured prompt sent to Claude for root cause analysis.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class IncidentContext:
    service:          str
    namespace:        str
    anomaly_score:    float
    alert_type:       str                # HighCPU | MemoryOOM | HighErrorRate | NodeNotReady
    cpu_pct:          float
    memory_pct:       float
    error_rate_pct:   float
    recent_logs:      str                # last 30 min of logs (truncated)
    recent_deploys:   str                # last 3 ArgoCD deployments
    p95_latency_ms:   Optional[float] = None


SYSTEM_PROMPT = """You are IntelliOps, an expert SRE AI assistant specialising in
Kubernetes and AWS infrastructure incident analysis. You receive structured incident
context and provide concise, actionable root cause analysis.

Always respond in this exact JSON format:
{
  "root_cause": "<1-2 sentence root cause>",
  "blast_radius": "<what services/users are affected>",
  "confidence": "<high|medium|low>",
  "recommended_actions": ["<action 1>", "<action 2>", "<action 3>"],
  "auto_remediation": "<what was or should be auto-remediated>",
  "escalate": <true|false>
}"""


def build_prompt(ctx: IncidentContext) -> str:
    return f"""Incident detected in the IntelliOps platform. Analyse and provide root cause.

## Alert
- Type: {ctx.alert_type}
- Service: {ctx.service}
- Namespace: {ctx.namespace}
- Anomaly Score: {ctx.anomaly_score:.4f}

## Current Metrics
- CPU Usage: {ctx.cpu_pct:.1f}%
- Memory Usage: {ctx.memory_pct:.1f}%
- Error Rate: {ctx.error_rate_pct:.2f}%
{f'- P95 Latency: {ctx.p95_latency_ms:.0f}ms' if ctx.p95_latency_ms else ''}

## Recent Deployments (last 3)
{ctx.recent_deploys or 'No recent deployments in the last 2 hours.'}

## Recent Logs (last 30 minutes — truncated to 3000 chars)
```
{ctx.recent_logs[:3000] if ctx.recent_logs else 'No logs available.'}
```

Based on the above, provide your root cause analysis in the required JSON format."""
