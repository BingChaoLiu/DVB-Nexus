"""dvbcsa adapter — dlopen + ctypes binding over the libdvbcsa SSE2
batch API (SPEC-610 §4/§8/§9, ADR-0011 §1, ticket #126).

License & graph discipline (ADR-0011 §1): libdvbcsa is GPLv2+ external
code loaded **dynamically** — importing this package performs no dlopen
(the binding stays out of the static import graph; the DLL load happens
only inside :func:`load_dvbcsa_backend` / :class:`DvbcsaBatchCipher`
construction), nothing is statically linked, and no libdvbcsa source or
binary enters the repository.  Local builds come from
``tools/build_dvbcsa_dll.sh`` (ruling §10-2: 产物不入库、CI 不构建).

DLL absence = honest explicit degradation (:class:`DvbcsaUnavailableError`
at load time — never a silent fallback to a fake backend; SPEC-610 §8,
ADR-0011 §1).  On CI the DLL-gated tests are NOT RUN with a visible skip
reason (ADR-0011 §5).

API surface used (libdvbcsa ``dvbcsa/dvbcsa.h``)::

    struct dvbcsa_bs_key_s * dvbcsa_bs_key_alloc(void);
    void dvbcsa_bs_key_set(const dvbcsa_cw_t cw, struct dvbcsa_bs_key_s *key);
    unsigned int dvbcsa_bs_batch_size(void);
    void dvbcsa_bs_encrypt(const struct dvbcsa_bs_batch_s *pcks,
                           const struct dvbcsa_bs_key_s *key,
                           unsigned int maxlen);
    void dvbcsa_bs_decrypt(const struct dvbcsa_bs_batch_s *pcks, ...);

The single-packet generic API is deliberately NOT used (research #106:
104 Mbps vs the 497 Mbps batch face — ADR-0011 §1 单包 API 不采用).
"""

from __future__ import annotations

from adapters.dvbcsa._binding import (
    DvbcsaBatchCipher,
    DvbcsaUnavailableError,
    load_dvbcsa_backend,
)

__all__ = [
    "DvbcsaBatchCipher",
    "DvbcsaUnavailableError",
    "load_dvbcsa_backend",
]
