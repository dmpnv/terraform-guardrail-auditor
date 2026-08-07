# Golden fixture for SSH-WORLD: exactly one finding expected (the bastion SG).

resource "aws_security_group" "bastion" {
  name = "bastion-sg"

  ingress {
    description = "ssh open to the world"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "internal" {
  name = "internal-sg"

  ingress {
    description = "ssh from corp range only"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/8"]
  }
}
