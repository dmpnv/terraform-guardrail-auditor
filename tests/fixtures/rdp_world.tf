# Golden fixture for RDP-WORLD: exactly one finding expected.

resource "aws_security_group" "winbox" {
  name = "winbox-sg"

  ingress {
    description = "rdp open to the world"
    from_port   = 3389
    to_port     = 3389
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
