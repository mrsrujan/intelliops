locals {
  prefix = "${var.project}-${var.environment}"
}

data "aws_caller_identity" "current" {}

# S3 bucket for model artifacts and training data
resource "aws_s3_bucket" "sagemaker" {
  bucket        = "${local.prefix}-sagemaker-${data.aws_caller_identity.current.account_id}"
  force_destroy = true
}

resource "aws_s3_bucket_versioning" "sagemaker" {
  bucket = aws_s3_bucket.sagemaker.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "sagemaker" {
  bucket = aws_s3_bucket.sagemaker.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

# IAM role for SageMaker
resource "aws_iam_role" "sagemaker" {
  name = "${local.prefix}-sagemaker"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "sagemaker.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "sagemaker_full" {
  role       = aws_iam_role.sagemaker.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSageMakerFullAccess"
}

resource "aws_iam_role_policy" "sagemaker_s3" {
  role = aws_iam_role.sagemaker.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
      Resource = [
        aws_s3_bucket.sagemaker.arn,
        "${aws_s3_bucket.sagemaker.arn}/*",
      ]
    }]
  })
}

# SageMaker Model — PyTorch LSTM autoencoder
resource "aws_sagemaker_model" "anomaly" {
  name               = "${local.prefix}-anomaly-detector"
  execution_role_arn = aws_iam_role.sagemaker.arn

  primary_container {
    # AWS-managed PyTorch inference container
    image          = "763104351884.dkr.ecr.${var.aws_region}.amazonaws.com/pytorch-inference:2.3.0-cpu-py311-ubuntu22.04-sagemaker"
    model_data_url = var.model_artifact_s3_uri
    environment = {
      SAGEMAKER_PROGRAM         = "inference.py"
      SAGEMAKER_SUBMIT_DIRECTORY = "/opt/ml/model/code"
    }
  }
}

# Endpoint configuration — single ml.t3.medium for dev
resource "aws_sagemaker_endpoint_configuration" "anomaly" {
  name = "${local.prefix}-anomaly-detector"

  production_variants {
    variant_name           = "AllTraffic"
    model_name             = aws_sagemaker_model.anomaly.name
    initial_instance_count = var.initial_instance_count
    instance_type          = var.instance_type
  }
}

# Real-time inference endpoint
resource "aws_sagemaker_endpoint" "anomaly" {
  name                 = "${local.prefix}-anomaly-detector"
  endpoint_config_name = aws_sagemaker_endpoint_configuration.anomaly.name
}

# CloudWatch alarm: endpoint invocation errors > 5 in 5 min
resource "aws_cloudwatch_metric_alarm" "endpoint_errors" {
  alarm_name          = "${local.prefix}-sagemaker-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ModelError"
  namespace           = "AWS/SageMaker"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  alarm_description   = "SageMaker endpoint returning errors"

  dimensions = {
    EndpointName = aws_sagemaker_endpoint.anomaly.name
    VariantName  = "AllTraffic"
  }
}
