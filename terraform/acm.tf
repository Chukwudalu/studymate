# Public TLS certificate for the API, so the ALB can serve HTTPS. Validated by
# DNS: ACM gives a CNAME that must exist in the domain's DNS (Namecheap here,
# so it's added by hand). The validation record for a given account + domain
# stays the same across rebuilds, so it only needs adding once.
resource "aws_acm_certificate" "api" {
  domain_name       = "api.steeze.ca"
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

output "acm_certificate_arn" {
  value = aws_acm_certificate.api.arn
}

output "acm_validation_records" {
  description = "CNAME record(s) to add in the domain's DNS to validate the certificate"
  value = [
    for o in aws_acm_certificate.api.domain_validation_options : {
      name  = o.resource_record_name
      type  = o.resource_record_type
      value = o.resource_record_value
    }
  ]
}
