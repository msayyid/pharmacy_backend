"""Inbound webhooks (payment gateways, etc.).

Webhook routes are NOT auth-gated by JWT or session — they're
authenticated via provider-issued signatures. Every handler must
verify the signature before doing anything else.
"""
