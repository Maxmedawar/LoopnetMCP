# Provider sync limitations

## Production decision

The provider-neutral synchronization foundation is implemented for review.
Production provider enablement is disabled.

The CRE MCP membership is individual. A `$197/month` `skool.com/cre` member may
use the CRE MCP only while that exact person is an active paying member. The
system binds provider authority to a server-owned user id. It does not use
email or client-supplied identity claims.

## What the foundation can enforce

- Trusted restrictive events revoke the linked individual's provider grant
  immediately.
- Cancellation, removal, ban, pause, subscription deletion, payment failure,
  and loss of the paid level do not depend on current plan mapping.
- Payment failure has no grace period.
- Final provider-authority loss revokes active OAuth sessions and pending
  authorization codes in the same transaction, which also prevents refresh.
- Stripe grants end at a trusted current billing-period end whose exact
  authority input is immutably bound to the receipt. Editable replay evidence
  cannot extend that date. When the trusted value is absent, grants use the
  bounded fallback lease.
- Skool grants expire at the bounded server lease when no later trusted event
  arrives.
- Stripe trialing does not grant the paid entitlement.
- An unpaid user in the same workspace cannot inherit another member's
  provider grant.

Fallback and Skool lease expiry are bounded stale-authority safeguards. They
are not immediate churn notification.

## Skool operating boundary

The official documented Skool Zapier surface described for this phase exposes
New Paid Member polling at roughly 10 to 15 minutes. It does not expose a
trusted cancellation, removal, ban, payment-failure, or current-roster feed.
Skool cancellation can retain community access until the billing-cycle end.

The runtime does not invent a Skool member-management API. Joining creates an
audited operator task that names the supported Skool Admin Invite or Zapier
Invite path. Completing the task binds the exact Skool member id to the
server-owned subject, but does not grant access. A signed member event or a
complete, current, confirmed operator review remains the next authority gate.

Current-state reconciliation stores a payload-free hash receipt plus counts,
source, observation time, confidence, and certainty. Stale, partial,
provisional, or unverified evidence is recorded as uncertain and cannot
strengthen access. A complete review can apply restrictive absence or status
changes. Unknown tiers revoke existing Skool authority and report a conflict.

Manual revocation immediately removes the linked Skool grant and invalidates
affected OAuth sessions and pending authorization codes in the same audited
transaction. Removing the member from the Skool community itself is still an
operator action in Skool's interface.

The optional signed relay remains an external dependency and stays disabled
until its secret is configured. The unconfigured route returns a fixed 404.
True automatic reconciliation also requires a trustworthy hosted source or a
scheduled operator runbook. Until private staging proves that path, the safe
posture is fail closed and describe uncertainty instead of claiming immediate
Skool churn detection.

## Prohibited shortcuts

- Do not scrape Skool.
- Do not bind authority to member email.
- Do not accept workspace or user authority from webhook claims.
- Do not assume Skool payout records in Stripe are individual member
  subscriptions.
- Do not describe the lease as immediate cancellation enforcement.
- Do not mark a review complete unless every current member in the configured
  community was checked.

Direct billing through the product's own Stripe integration is the only
currently documented path in scope that can meet immediate revocation end to
end.
