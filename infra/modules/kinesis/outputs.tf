output "metrics_stream_arn"  { value = aws_kinesis_stream.metrics.arn }
output "metrics_stream_name" { value = aws_kinesis_stream.metrics.name }
output "alerts_stream_arn"   { value = aws_kinesis_stream.alerts.arn }
output "alerts_stream_name"  { value = aws_kinesis_stream.alerts.name }
output "sns_topic_arn"       { value = aws_sns_topic.anomaly_alerts.arn }
output "metric_windows_table" { value = aws_dynamodb_table.metric_windows.name }
output "rca_audit_table"      { value = aws_dynamodb_table.rca_audit.name }
