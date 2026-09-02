variable "project"     { type = string }
variable "environment" { type = string }
variable "aws_region"  { type = string }

variable "model_artifact_s3_uri" {
  description = "s3://bucket/prefix/model.tar.gz — uploaded by training job"
  type        = string
}

variable "instance_type" {
  type    = string
  default = "ml.t3.medium"
}

variable "initial_instance_count" {
  type    = number
  default = 1
}
