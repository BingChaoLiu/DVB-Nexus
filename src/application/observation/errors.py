"""Gateway structured-rejection vocabulary (SPEC-300 §4.1/§8/§13).

The gateway returns ``accepted`` / ``duplicate`` / ``rejected`` structured
results (OBSERVATION-INTEGRATION-CONTRACT §6); a rejected result carries one
canonical ``OBS_*`` code. Envelope-contract codes come from the single shared
vocabulary :class:`domain.observation.errors.EnvelopeErrorCode` (#46 frozen
surface — no parallel copy is kept here). This module only owns the codes the
gateway itself is the authority for:

- ``OBS_QUEUE_FULL`` — the bounded ingestion queue is full and the event may
  not be coalesced (SPEC-300 §8: 有界队列满时显式错误非静默丢弃; registered in
  SPEC-300 §13 by ticket #47);
- ``OBS_STORAGE_UNAVAILABLE`` — the journal cannot commit (SPEC-300 §8);
  reusing the §13-listed code, ``retryable=True`` (producer retries per
  OBSERVATION-INTEGRATION-CONTRACT §5).
"""

OBS_QUEUE_FULL = "OBS_QUEUE_FULL"
OBS_STORAGE_UNAVAILABLE = "OBS_STORAGE_UNAVAILABLE"

__all__ = ["OBS_QUEUE_FULL", "OBS_STORAGE_UNAVAILABLE"]
