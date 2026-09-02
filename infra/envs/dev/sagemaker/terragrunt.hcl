include "env" {
  path   = find_in_parent_folders()
  expose = true
}

terraform {
  source = "../../../modules//sagemaker"
}

inputs = {
  # Upload model.tar.gz to this path after running ai/anomaly-model/train.py
  model_artifact_s3_uri = "s3://intelliops-sagemaker-ACCOUNT_ID/models/anomaly-detector/model.tar.gz"
  instance_type          = "ml.t3.medium"
  initial_instance_count = 1
}
