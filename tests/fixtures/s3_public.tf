# Golden fixture for S3-PUBLIC: two findings expected (ACL flavor and
# bucket-policy flavor); both buckets carry SSE companions so no other rule fires.

resource "aws_s3_bucket" "web" {
  bucket = "acme-public-web"
  acl    = "public-read"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "web" {
  bucket = aws_s3_bucket.web.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket" "assets" {
  bucket = "acme-assets"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "assets" {
  bucket = aws_s3_bucket.assets.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_policy" "assets_public" {
  bucket = aws_s3_bucket.assets.id
  policy = <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": "*",
      "Action": ["s3:GetObject"],
      "Resource": "arn:aws:s3:::acme-assets/*"
    }
  ]
}
POLICY
}
