# Negative fixture (SPEC.md, interpretation 2 condition): a bucket plus its
# aws_s3_bucket_server_side_encryption_configuration in the same file must
# produce zero findings for S3-NO-ENCRYPTION.

resource "aws_s3_bucket" "reports" {
  bucket = "acme-reports"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "reports" {
  bucket = aws_s3_bucket.reports.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
  }
}
