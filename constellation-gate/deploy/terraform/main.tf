locals {
  instance_name = "${var.service_name}-${var.environment}"
  gate_port     = var.container_port
}

resource "digitalocean_droplet" "gate" {
  name     = local.instance_name
  region   = var.region
  size     = var.instance_size
  image    = var.image
  ssh_keys = var.ssh_key_ids
  tags     = ["constellation-gate", var.environment]

  user_data = templatefile("${path.module}/cloud-init.yaml.tftpl", {
    repo_url = var.repo_url
    branch   = var.branch
  })
}

resource "cloudflare_record" "gate" {
  count   = var.create_dns_record ? 1 : 0
  zone_id = var.cloudflare_zone_id
  name    = var.service_domain
  type    = "A"
  value   = digitalocean_droplet.gate.ipv4_address
  ttl     = 300
  proxied = false
}

resource "digitalocean_firewall" "gate" {
  name = "${local.instance_name}-fw"

  droplet_ids = [digitalocean_droplet.gate.id]

  inbound_rule {
    protocol         = "tcp"
    port_range       = tostring(var.host_port)
    source_addresses = var.allowed_cidrs
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = var.admin_cidrs
  }

  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}
