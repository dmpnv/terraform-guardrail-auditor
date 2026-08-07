# Golden fixture for EBS-NO-ENCRYPTION: two findings expected
# (attribute absent, and encrypted = false); the third volume is compliant.

resource "aws_ebs_volume" "scratch" {
  availability_zone = "us-east-1a"
  size              = 100
}

resource "aws_ebs_volume" "cache" {
  availability_zone = "us-east-1a"
  size              = 50
  encrypted         = false
}

resource "aws_ebs_volume" "data" {
  availability_zone = "us-east-1a"
  size              = 200
  encrypted         = true
}
