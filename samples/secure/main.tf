# Compliant counterpart to samples/insecure — every guardrail passes.

variable "db_password" {
  type      = string
  sensitive = true
}

resource "aws_kms_key" "data" {
  description         = "Data encryption key"
  enable_key_rotation = true
}

resource "aws_s3_bucket" "reports" {
  bucket = "acme-finance-reports-secure"

  tags = {
    team = "finance"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "reports" {
  bucket = aws_s3_bucket.reports.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.data.arn
    }
  }
}

resource "aws_s3_bucket_public_access_block" "reports" {
  bucket                  = aws_s3_bucket.reports.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_security_group" "edge" {
  name        = "edge-sg"
  description = "Edge security group"

  ingress {
    description = "ssh from corporate range only"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["10.20.0.0/16"]
  }
}

resource "aws_iam_policy" "reports_reader" {
  name   = "reports-reader"
  policy = <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": "arn:aws:s3:::acme-finance-reports-secure/*"
    }
  ]
}
POLICY
}

resource "aws_db_instance" "billing" {
  identifier          = "billing-db"
  engine              = "postgres"
  instance_class      = "db.t3.medium"
  allocated_storage   = 100
  username            = "master"
  password            = var.db_password
  publicly_accessible = false
  storage_encrypted   = true
  skip_final_snapshot = false
}

resource "aws_instance" "worker" {
  ami           = "ami-0abcdef1234567890"
  instance_type = "t3.large"

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  root_block_device {
    volume_size = 60
    encrypted   = true
  }
}

resource "aws_ebs_volume" "scratch" {
  availability_zone = "us-east-1a"
  size              = 200
  encrypted         = true
}
