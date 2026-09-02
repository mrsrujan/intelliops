#!/usr/bin/env bash
# Deploy the full observability stack to the local Kubernetes cluster
set -euo pipefail

NAMESPACE=monitoring

echo "==> Adding Helm repos"
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add fluent              https://fluent.github.io/helm-charts
helm repo update

echo "==> Creating monitoring namespace"
kubectl create namespace ${NAMESPACE} --dry-run=client -o yaml | kubectl apply -f -

echo "==> Installing kube-prometheus-stack (Prometheus + Grafana + AlertManager)"
helm upgrade --install kube-prometheus-stack \
  prometheus-community/kube-prometheus-stack \
  --version 61.3.2 \
  --namespace ${NAMESPACE} \
  -f "$(dirname "$0")/prometheus/values.yaml" \
  --wait --timeout 5m

echo "==> Applying ServiceMonitors"
kubectl apply -f "$(dirname "$0")/prometheus/servicemonitor-payment.yaml"
kubectl apply -f "$(dirname "$0")/prometheus/servicemonitor-order.yaml"

echo "==> Applying Grafana dashboard ConfigMap"
kubectl apply -f "$(dirname "$0")/grafana/intelliops-dashboard.yaml"

echo "==> Applying OTEL Collector"
kubectl apply -f "$(dirname "$0")/otel/collector.yaml"

echo ""
echo "==> Installing Fluent Bit (log shipper — skip on local if no CloudWatch access)"
read -p "Install Fluent Bit? Requires AWS CloudWatch access [y/N]: " install_fb
if [[ "${install_fb}" =~ ^[Yy]$ ]]; then
  helm upgrade --install fluent-bit fluent/fluent-bit \
    --namespace ${NAMESPACE} \
    -f "$(dirname "$0")/fluent-bit/values.yaml" \
    --wait
fi

echo ""
echo "===== Observability stack deployed! ====="
echo ""
echo "Access Grafana:"
echo "  kubectl port-forward svc/kube-prometheus-stack-grafana 3001:80 -n ${NAMESPACE}"
echo "  Open: http://localhost:3001  (user: admin  password: intelliops-admin)"
echo ""
echo "Access Prometheus:"
echo "  kubectl port-forward svc/kube-prometheus-stack-prometheus 9090:9090 -n ${NAMESPACE}"
echo "  Open: http://localhost:9090"
echo ""
echo "Access AlertManager:"
echo "  kubectl port-forward svc/kube-prometheus-stack-alertmanager 9093:9093 -n ${NAMESPACE}"
echo "  Open: http://localhost:9093"
