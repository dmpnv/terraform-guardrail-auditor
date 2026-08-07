# Worked example from the README: hand-computed score 40.5 = 100 x (1 - 22/37).
# The public ACL is the inline acl attribute on the bucket (NOT a separate
# aws_s3_bucket_acl resource) so the denominator stays exactly 37.

resource "aws_s3_bucket" "web" {
  bucket = "acme-worked-example"
  acl    = "public-read"
}

resource "aws_security_group" "edge" {
  name = "edge-sg"

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_ebs_volume" "data" {
  availability_zone = "us-east-1a"
  size              = 100
  encrypted         = true
}
