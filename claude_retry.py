"""
Shared retry policy for Claude API calls across the Scout pipeline.

External APIs are occasionally flaky (network timeouts, 502/529 Anthropic-side
errors, transient rate limits). Without a retry, a single hiccup crashes
label_clusters() or reason() and aborts the whole pipeline before it can write
a brief or send alerts — even though the failure had nothing to do with the
data itself and a retry a few seconds later would likely succeed.

Used by:
  cluster.py -> label_clusters()
  scout.py   -> reason()
"""

from anthropic import (
    Anthropic,
    APIConnectionError,
    APITimeoutError,
    RateLimitError,
    InternalServerError,
)
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# Errors worth retrying: connection drops, timeouts, rate limits, and
# Anthropic-side 5xx errors. Deliberately NOT retried: bad requests, auth
# errors, etc — those won't fix themselves by waiting.
RETRYABLE_ERRORS = (APIConnectionError, APITimeoutError, RateLimitError, InternalServerError)

MAX_ATTEMPTS = 4  # original call + up to 3 retries


def _before_sleep(retry_state):
    exc = retry_state.outcome.exception()
    wait = retry_state.next_action.sleep if retry_state.next_action else 0
    print(f"[claude_retry] {exc.__class__.__name__} on attempt "
          f"{retry_state.attempt_number}/{MAX_ATTEMPTS} — retrying in {wait:.1f}s")


@retry(
    retry=retry_if_exception_type(RETRYABLE_ERRORS),
    wait=wait_exponential(multiplier=1, min=2, max=20),
    stop=stop_after_attempt(MAX_ATTEMPTS),
    before_sleep=_before_sleep,
    reraise=True,
)
def call_claude(client: Anthropic, **kwargs):
    """client.messages.create(**kwargs) with automatic exponential-backoff
    retry on transient errors (network/timeout/rate-limit/5xx).

    Non-retryable errors (e.g. bad request, auth) raise immediately on the
    first attempt. If all retries are exhausted, the last exception is
    re-raised — callers (label_clusters, reason) already wrap this in their
    own try/except and degrade gracefully instead of crashing main()."""
    return client.messages.create(**kwargs)
