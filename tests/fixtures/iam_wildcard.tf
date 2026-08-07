# Golden fixture for IAM-WILDCARD: exactly one finding expected
# (the scoped reader policy is compliant).

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

resource "aws_iam_role_policy" "reader" {
  name   = "reader"
  role   = "app-role"
  policy = <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": "arn:aws:s3:::acme-app/*"
    }
  ]
}
POLICY
}
