locals {
  prefix = "${var.project}-${var.environment}"
}

# Stream 1: raw Prometheus metrics → Lambda → SageMaker
resource "aws_kinesis_stream" "metrics" {
  name             = "${local.prefix}-metrics"
  shard_count      = var.metrics_shard_count
  retention_period = var.retention_hours

  stream_mode_details {
    stream_mode = "PROVISIONED"
  }

  encryption_type = "KMS"
  kms_key_id      = "alias/aws/kinesis"
}

# Stream 2: remediation events (SageMaker alert → downstream consumers)
resource "aws_kinesis_stream" "alerts" {
  name             = "${local.prefix}-alerts"
  shard_count      = var.alerts_shard_count
  retention_period = var.retention_hours

  stream_mode_details {
    stream_mode = "PROVISIONED"
  }

  encryption_type = "KMS"
  kms_key_id      = "alias/aws/kinesis"
}

# SNS topic — anomaly alerts published here, triggers RCA Lambda
resource "aws_sns_topic" "anomaly_alerts" {
  name              = "${local.prefix}-anomaly-alerts"
  kms_master_key_id = "alias/aws/sns"
}

# DynamoDB: sliding window state for anomaly_handler Lambda
resource "aws_dynamodb_table" "metric_windows" {
  name         = "${local.prefix}-metric-windows"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "service"

  attribute {
    name = "service"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
}

# DynamoDB: RCA audit trail
resource "aws_dynamodb_table" "rca_audit" {
  name         = "${local.prefix}-rca-audit"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "rca_id"

  attribute {
    name = "rca_id"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
}
