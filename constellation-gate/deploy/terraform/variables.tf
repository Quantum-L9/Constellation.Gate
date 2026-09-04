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
  # No default on purpose. The previous default of ["0.0.0.0/0", "::/0"]
  # exposed the Gate port to the whole internet unless an operator remembered
  # to override it; the caller must now name the networks that may reach it.
  description = "CIDRs allowed to reach the public Gate port (must be supplied; no world-open default)"
  type        = list(string)

  validation {
    condition     = length(var.allowed_cidrs) > 0 && !contains(var.allowed_cidrs, "0.0.0.0/0") && !contains(var.allowed_cidrs, "::/0")
    error_message = "allowed_cidrs must list the specific networks that may reach the Gate port; 0.0.0.0/0 and ::/0 are refused."
  }
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
