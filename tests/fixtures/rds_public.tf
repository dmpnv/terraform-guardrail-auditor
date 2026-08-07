# Golden fixture for RDS-PUBLIC: exactly one finding expected.

resource "aws_db_instance" "reporting" {
  identifier          = "reporting-db"
  engine              = "postgres"
  instance_class      = "db.t3.medium"
  allocated_storage   = 50
  publicly_accessible = true
  skip_final_snapshot = true
}
