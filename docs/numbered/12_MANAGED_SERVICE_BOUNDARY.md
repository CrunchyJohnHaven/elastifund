# 12 Managed Service Boundary
Version: 1.0.0
Date: 2026-03-09
Source: `research/elastic_vision_document.md`, `research/platform_vision_document.md`, `CLAUDE.md`, `README.md`
Purpose: Define what stays open source, what may be offered as hosted infrastructure, and how that boundary should be explained.
Related docs: `05_NON_TRADING_WORKERS.md`, `09_GOVERNANCE_AND_SAFETY.md`, `11_PUBLIC_MESSAGING.md`

## Why This Boundary Exists

Elastifund should remain a credible open-source system without publishing everything that would make operation unsafe or commercially unserious.
The project needs a clear answer for contributors and future customers:
what belongs in the public commons and what belongs in a hosted or operator-managed layer.

## What Stays Open Source

The public layer should include:

- architecture and repo layout
- worker framework and interfaces
- evaluation logic and scorecard definitions
- paper-mode workflows
- default dashboards and telemetry schema
- numbered docs and public diary
- prompt system and review discipline
- educational content, failures, and benchmark methodology

This is the part that makes the system useful as a public learning surface.

## What Stays Private Or Operator-Managed

The private layer should include:

- secrets and credentials
- wallet keys and signing material
- customer-specific data and operator-only access policies
- deliverability operations for live outbound programs
- hosted infrastructure operations
- premium templates or account-specific playbooks
- enterprise guardrails that depend on customer context

## Hosted Layer Opportunity

If the open-source system proves useful, a managed layer can responsibly offer:

- hosted deployment
- monitored dashboards
- safer configuration defaults
- deliverability and domain operations
- premium support and onboarding
- enterprise approval workflows

The hosted layer should feel like operational convenience and stronger governance, not a hidden rewrite of the product.

## Customer And Contributor Rule

Contributors should be able to learn, run, and improve the system from the public repo.
Customers should be able to pay for hosted reliability, onboarding, and operations without losing clarity about what is public versus managed.

## Data Ownership Rule

Public artifacts should use public or repo-owned evidence.
Customer-specific data should remain customer-owned and isolated.
The managed layer should not quietly mix private customer data into public benchmarks.

## Messaging Rule

Public messaging should say that the framework is open and the hosted layer, if offered, provides infrastructure and operations.
Do not blur the line by implying that the repo alone includes production customer operations.

## Governance Connection

This boundary supports the open-source guardrails described in `09_GOVERNANCE_AND_SAFETY.md`.
The point is not secrecy.
The point is to keep the public system educational and trustworthy while keeping sensitive operations out of the repo.

Last verified: 2026-03-09 against `research/elastic_vision_document.md`, `research/platform_vision_document.md`, and `CLAUDE.md`.
Next review: 2026-06-09.
