# Golden fixture for the IPv6 variant of SSH-WORLD: exactly one finding
# expected (the scoped IPv6 range is compliant).

resource "aws_security_group" "v6_bastion" {
  name = "v6-bastion-sg"

  ingress {
    description      = "ssh open to the world over ipv6"
    from_port        = 22
    to_port          = 22
    protocol         = "tcp"
    ipv6_cidr_blocks = ["::/0"]
  }
}

resource "aws_security_group" "v6_internal" {
  name = "v6-internal-sg"

  ingress {
    description      = "ssh from corp ipv6 range only"
    from_port        = 22
    to_port          = 22
    protocol         = "tcp"
    ipv6_cidr_blocks = ["2001:db8:1234::/48"]
  }
}
