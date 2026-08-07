# Intentionally NON-COMPLIANT Terraform used to demo the guardrail auditor.
# Every guardrail in the built-in pack should fire against this stack.
# DO NOT deploy.

resource "aws_s3_bucket" "reports" {
  bucket = "acme-finance-reports"
  acl    = "public-read" # GR-S3-001; no SSE (GR-S3-002); no public access block (GR-S3-003)

  tags = {
    team = "finance"
  }
}

resource "aws_security_group" "edge" {
  name        = "edge-sg"
  description = "Edge security group"

  ingress {
    description = "ssh from anywhere"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"] # GR-NET-001
  }

  ingress {
    description = "app port open wide"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"] # GR-NET-002
  }
}

resource "aws_iam_policy" "ops_admin" {
  name   = "ops-admin"
  policy = <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "*",
      "Resource": "*"
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
  password            = "SuperSecret123!" # GR-SEC-001
  publicly_accessible = true              # GR-RDS-001
  skip_final_snapshot = true
  # storage_encrypted not set             # GR-RDS-002
}

resource "aws_instance" "worker" {
  ami           = "ami-0abcdef1234567890"
  instance_type = "t3.large"

  root_block_device {
    volume_size = 60 # encrypted not set -> GR-EBS-001
  }
  # no metadata_options block -> GR-EC2-001
}

resource "aws_ebs_volume" "scratch" {
  availability_zone = "us-east-1a"
  size              = 200
  encrypted         = false # GR-EBS-001
}
