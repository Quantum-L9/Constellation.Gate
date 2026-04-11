variable "environment" {
  description = "Deployment environment name"
  type        = string
  default     = "production"
}

variable "service_name" {
  description = "Service name used for host naming"
  type        = string
  default     = "constellation-gate"
}

variable "region" {
  description = "Cloud region"
  type        = string
  default     = "nyc3"
}

variable "instance_size" {
  description = "Droplet instance size"
  type        = string
  default     = "s-2vcpu-4gb"
}

variable "image" {
  description = "Droplet image slug"
  type        = string
  default     = "ubuntu-24-04-x64"
}

variable "ssh_key_ids" {
  description = "SSH key IDs to inject into the instance"
  type        = list(string)
}

variable "repo_url" {
  description = "Git repository URL to clone on bootstrap"
  type        = string
}

variable "branch" {
  description = "Git branch or ref to deploy"
  type        = string
  default     = "main"
}

variable "host_port" {
  description = "Public host port exposed for Gate"
  type        = number
  default     = 9000
}

variable "container_port" {
  description = "Container port Gate listens on"
  type        = number
  default     = 9000
}

variable "allowed_cidrs" {
  description = "CIDRs allowed to reach the public Gate port"
  type        = list(string)
  default     = ["0.0.0.0/0", "::/0"]
}

variable "admin_cidrs" {
  description = "CIDRs allowed SSH access"
  type        = list(string)
  default     = ["0.0.0.0/0", "::/0"]
}

variable "create_dns_record" {
  description = "Whether to create a Cloudflare DNS record"
  type        = bool
  default     = false
}

variable "service_domain" {
  description = "DNS name for the service when create_dns_record is true"
  type        = string
  default     = ""
}

variable "cloudflare_zone_id" {
  description = "Cloudflare zone id"
  type        = string
  default     = ""
}
