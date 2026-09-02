output "endpoint_name"    { value = aws_sagemaker_endpoint.anomaly.name }
output "endpoint_arn"     { value = aws_sagemaker_endpoint.anomaly.arn }
output "s3_bucket"        { value = aws_s3_bucket.sagemaker.bucket }
output "sagemaker_role_arn" { value = aws_iam_role.sagemaker.arn }
