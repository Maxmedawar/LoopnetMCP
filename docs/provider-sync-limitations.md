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
- Provider grants expire at a bounded server lease even when no later event
  arrives.
- An unpaid user in the same workspace cannot inherit another member's
  provider grant.

Lease expiry is a bounded stale-authority safeguard. It is not immediate churn
notification.

## Why Skool is not production-ready

The official documented Skool Zapier surface described for this phase exposes
New Paid Member polling at roughly 10 to 15 minutes. It does not expose a
trusted cancellation, removal, ban, payment-failure, or current-roster feed.
Skool cancellation can retain community access until the billing-cycle end.

The signed relay and current-member source consumed by this code are external
dependencies. They are not implemented in this repository. Without a
trustworthy current-state or restrictive signal, immediate Skool revocation
cannot be guaranteed. The safe production posture is to fail closed and keep
the Skool webhook secret unset. The unconfigured route returns a fixed 404.

## Prohibited shortcuts

- Do not scrape Skool.
- Do not bind authority to member email.
- Do not accept workspace or user authority from webhook claims.
- Do not assume Skool payout records in Stripe are individual member
  subscriptions.
- Do not describe the lease as immediate cancellation enforcement.

Direct billing through the product's own Stripe integration is the only
currently documented path in scope that can meet immediate revocation end to
end.
