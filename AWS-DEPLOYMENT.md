# AWS deployment plan (not deployed)

This plan maps the local CareQueue prototype to a small AWS demo. It is not a production healthcare design, and it has not created AWS resources.

## Target architecture

```text
Browser (fictional demo data only)
        │ HTTPS recommended for a public demo
        ▼
EC2 Linux VM (Docker Engine + CareQueue container)
        ├── EBS gp3 volume → SQLite demo database
        ├── IAM instance role → Systems Manager + CloudWatch permissions
        └── CloudWatch Agent → container / host logs and metrics
CloudWatch Synthetics canary → GET /health, latency and availability checks
```

Suggested components: Amazon VPC/security group, Amazon EC2, Amazon EBS, AWS Systems Manager, and Amazon CloudWatch (including a canary). EC2 supplies the VM; Docker isolates the app; EBS persists SQLite data; Systems Manager avoids opening SSH; CloudWatch records operational evidence and can probe `/health`.

## SLA and TTR measurement design

- **Availability target (proposed):** at least 99.5% per calendar month, computed from scheduled synthetic checks. State the check interval and exclusions in the report.
- **Response target (proposed):** `/health` P95 below 2 seconds over a named measurement window. Also run the read-only appointment-list workload; `/health` alone does not represent user workload.
- **Recovery target (proposed):** TTR at or below 120 seconds for a recovered incident.
- **TTR rule:** first failed canary check to first confirmed healthy check after recovery. Keep incident timestamps and recovery method. Monthly average TTR = total TTR for recovered incidents / recovered incidents; report unrecovered incidents separately.
- **Evidence:** CloudWatch Synthetics results, CloudWatch metrics/logs, and an incident timeline. Local Docker evidence is not AWS evidence.

## Safe deployment checklist

1. Choose AWS region and an explicit spending cap; check the AWS Pricing Calculator and account Free Tier eligibility.
2. Deploy one small Linux EC2 instance, an encrypted gp3 EBS data volume, a least-privilege instance role, and a security group. Prefer Systems Manager Session Manager over public SSH.
3. Restrict the demo endpoint to a known source IP, or add HTTPS and authentication before making it public. Never load real patient information.
4. Install Docker and CloudWatch Agent, run the Compose app, and verify `/health`.
5. Create a CloudWatch Synthetics canary and alarm. Run a controlled failure/recovery exercise and save the CloudWatch evidence.
6. Stop or delete resources after the demonstration; EBS volumes, public IPv4, logs, and canary runs may continue to incur charges.

## Free-tier use

Use only resources shown as eligible in your own AWS account and selected region. AWS says new accounts receive $100 in credits and can earn up to $100 more; the Free plan lasts up to six months or until credits run out. Eligibility differs for older accounts, and some services/features may be unavailable on the Free plan. CloudWatch Synthetics may add canary, Lambda, log, and metric usage, so skip the canary if your account labels it paid-only or its usage is not covered. A credit balance is not the same as a hard spending cap. Check plan, remaining credits, free-tier limits, and selected-region pricing before starting; stop and delete resources after the class demo.

AWS publishes a t3.micro example rate of $0.0104/hour and gp3 storage example of $0.08/GB-month on its pricing pages; these are reference examples, not a quote for your region/account. See the links below and confirm every planned service in AWS Pricing Calculator.

## Current status

Local Docker app, monitoring panel, a local recovery event, and local read-only load test are complete. EC2 deployment, CloudWatch canary/alarms, AWS measured SLA/TTR, and AWS cost confirmation are pending an AWS account, region, and approved spend cap.

## Sources

- [AWS Free Tier plans and credits](https://aws.amazon.com/free/)
- [EC2 Free Tier eligibility by account date](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-free-tier-usage.html)
- [Amazon EC2 T3 instance types and example pricing](https://aws.amazon.com/ec2/instance-types/t3/)
- [Amazon EBS pricing](https://aws.amazon.com/ebs/pricing/)
- [CloudWatch Synthetics canaries](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Synthetics_Canaries.html)
- [Amazon CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)
