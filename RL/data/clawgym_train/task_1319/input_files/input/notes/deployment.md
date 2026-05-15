# Deployment Guide

This document covers how to deploy NebulaDrive into your environment using our Helm charts and Terraform modules.

Supported cloud providers: AWS, GCP, and Azure.

## Prerequisites
- Kubernetes 1.26 or newer.
- External Postgres 14+ and Redis 6+ or managed equivalents.
- Object storage bucket (S3, GCS, or Azure Blob) configured.

## High-Level Steps
1. Provision network, DNS, and certificates.
2. Deploy Postgres, Redis, and object storage.
3. Install NebulaDrive services via Helm.
4. Configure SSO, RBAC defaults, and security policies.

## Sizing Guidance
- Start with 3 replicas per stateless service.
- Use provisioned IOPS for metadata database.
- Scale object storage throughput based on expected concurrency.