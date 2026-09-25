"""GitHub webhook gateway: authenticate, deduplicate and enqueue failures.

Transport only (AD-17): constant-time signature check, accepted-event
registry, installation and load checks, and exactly one enqueue call.
No business/state-machine logic, no LLM or GitHub client (story 1.1).
"""
