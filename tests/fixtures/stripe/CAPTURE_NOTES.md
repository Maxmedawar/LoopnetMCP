# Stripe fixture provenance

The subscription-list fixtures are representative test-mode responses based on
Stripe's official subscription object and list schemas. They contain invented
identifiers and no customer data.

The fixtures use item-level `current_period_end`, which Stripe introduced in
the Basil API family and retained in Clover.

VERIFY with a real Stripe test account before private staging. The runtime is
disabled without an explicitly supplied `sk_test_` or `rk_test_` key, rejects
live-mode objects, and contains no Stripe write operation.
