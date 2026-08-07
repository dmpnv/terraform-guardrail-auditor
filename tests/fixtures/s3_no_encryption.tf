# Golden fixture for S3-NO-ENCRYPTION: exactly one finding expected.

resource "aws_s3_bucket" "logs" {
  bucket = "acme-app-logs"
}
