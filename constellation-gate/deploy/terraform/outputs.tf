output "gate_ipv4_address" {
  description = "Public IPv4 address of the Gate droplet"
  value       = digitalocean_droplet.gate.ipv4_address
}

output "gate_service_url" {
  description = "Service URL for the Gate deployment"
  value = var.create_dns_record
    ? "http://${var.service_domain}"
    : "http://${digitalocean_droplet.gate.ipv4_address}:${var.host_port}"
}

output "gate_instance_name" {
  description = "Provisioned instance name"
  value       = digitalocean_droplet.gate.name
}
