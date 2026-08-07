# Clean fixture: zero findings expected across the whole pack.

resource "aws_s3_bucket" "data" {
  bucket = "acme-clean-data"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
  }
}

resource "aws_security_group" "edge" {
  name = "edge-sg"

  ingress {
    description = "ssh from corp range"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["10.20.0.0/16"]
  }
}

resource "aws_ebs_volume" "data" {
  availability_zone = "us-east-1a"
  size              = 100
  encrypted         = true
}

resource "aws_db_instance" "app" {
  identifier          = "app-db"
  engine              = "postgres"
  instance_class      = "db.t3.small"
  allocated_storage   = 20
  publicly_accessible = false
  skip_final_snapshot = true
}

resource "aws_iam_policy" "reader" {
  name   = "app-reader"
  policy = <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": "arn:aws:s3:::acme-clean-data/*"
    }
  ]
}
POLICY
}
