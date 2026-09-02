variable "project"     { type = string }
variable "environment" { type = string }

variable "metrics_shard_count" {
  type    = number
  default = 1
}

variable "alerts_shard_count" {
  type    = number
  default = 1
}

variable "retention_hours" {
  type    = number
  default = 24
}
