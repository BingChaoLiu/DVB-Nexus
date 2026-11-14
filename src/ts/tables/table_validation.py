"""SPEC-103 — PID association validator (§8): diagnostics, no backfill.

Independent validator across one PAT and the PMT sections recovered from
the stream (§8 items 1-7). Unlike the builders/parsers (which raise
:class:`ts.errors.InvalidSectionError` on malformed wire data), the
validator works on already-parsed table objects and reports semantic
findings as :class:`ts.issues.ValidationIssue` diagnostics (§8.7: "不存在的
PMT 或不匹配 program_number 应产生诊断 issue，而不是用默认 PMT 补齐" — a
missing or mismatched PMT is never backfilled with a default).

Findings and their §9 codes (all severity ``"error"`` — an association
violation is a real defect; this is the detection surface the #9 ruling's
PMT_PID_MISMATCH fault relies on):

- ``PAT_PID_INVALID`` — the PAT is not carried on PID ``0x0000`` (§8.1).
- ``PAT_PMTPID_INVALID`` — a non-zero PAT entry maps to the PAT fixed PID
  ``0x0000`` or the Null PID ``0x1FFF`` (§7 table-specific PID profile).
- ``PAT_PROGRAM_NUMBER_INVALID`` — duplicate ``program_number`` entries in
  the PAT loop make the program→PID mapping ambiguous (§8.2).
- ``PAT_PMT_PROGRAM_MISMATCH`` — one clause, three shapes (§8.7): a PAT
  entry with no PMT found for its program; a PMT found on a different PID
  than the PAT maps it to; a PMT claiming a program_number with no PAT
  entry. A wire PMT claiming ``program_number=0`` raises this same code at
  parse time in :func:`ts.tables.pmt.parse_pmt` (§5: program 0 is the PAT's
  network_PID slot).
- ``PMT_PID_INVALID`` — ES/PCR PID policy violations (§8.4/§8.5/§8.6):
  ``pcr_pid`` or an ``elementary_PID`` of ``0x0000``/``0x1FFF``, or a
  duplicated ``elementary_PID`` within one program. ``pcr_pid == 0x1FFF``
  is the project's tightened rule — H.222.0 §2.4.4.8 explicitly permits
  0x1FFF for programs without PCR, so the message must not present it as a
  standard violation (ruling #11 wording constraint).

Association shape: ``program_number=0`` PAT entries are the network_PID
pointer and are skipped (never matched against PMTs, §3); ``pcr_pid``
riding one of the program's ES PIDs is legal (§8.6 second clause) and is
not reported. Multi-section PMTs are legal input: several
``(pid, PMTSection)`` pairs sharing one ``program_number``.

PID policy constants: :data:`NULL_PID` (``0x1FFF``) and the PAT fixed PID
(:data:`ts.tables.pat.PAT_PID`, ``0x0000``). Error-code constants live in
:mod:`ts.tables.pat` (``PAT_*`` / ``TABLE_*`` family owner) and
:mod:`ts.tables.pmt` (``PMT_*`` owner); this module defines none itself.
"""

from __future__ import annotations

from typing import Sequence

from ts.issues import ValidationIssue
from ts.tables.pat import (
    PAT_PID,
    PAT_PID_INVALID,
    PAT_PMT_PROGRAM_MISMATCH,
    PAT_PMTPID_INVALID,
    PAT_PROGRAM_NUMBER_INVALID,
    PATSection,
)
from ts._bytesutil import PID_MAX
from ts.tables.pmt import PMT_PID_INVALID, PMTSection

#: Null-packet PID (project PID policy constant, SPEC-103 §7/§8.6).
NULL_PID = 0x1FFF


def _check_pid(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be int, got {type(value).__name__}")
    if not 0 <= value <= PID_MAX:
        raise ValueError(f"{name} must be in 0..{PID_MAX} (13-bit), got {value}")
    return value


def validate_pid_associations(
    pat_pid: int,
    pat: PATSection,
    pmts: Sequence[tuple[int, PMTSection]],
) -> list[ValidationIssue]:
    """Validate the PAT↔PMT↔ES association set (SPEC-103 §8).

    Args:
        pat_pid: PID the PAT section was recovered from (§8.1: must be
            ``0x0000``).
        pat: the parsed PAT (one section or the aggregated set's entries).
        pmts: ``(carrying_pid, PMTSection)`` pairs for every PMT section
            recovered from the stream; several pairs may share a
            ``program_number`` (legal multi-section PMT).

    Returns:
        Zero or more ValidationIssue diagnostics (severity ``"error"``),
        in a stable check order: PAT placement, PAT loop integrity, PAT
        entry associations, then per-PMT PID policy. An empty list means
        no violation was found.

    Raises:
        TypeError: ``pat_pid``/``pmts`` shapes are wrong or ``pat`` is not
            a PATSection.
        ValueError: a PID argument is out of the 13-bit range.
    """
    _check_pid(pat_pid, "pat_pid")
    if not isinstance(pat, PATSection):
        raise TypeError(f"pat must be PATSection, got {type(pat).__name__}")
    checked_pmts: list[tuple[int, PMTSection]] = []
    for entry in pmts:
        if not isinstance(entry, tuple) or len(entry) != 2:
            raise TypeError(
                "pmts entries must be (pid, PMTSection) tuples, got "
                f"{entry!r}"
            )
        pid, pmt = entry
        _check_pid(pid, "pmts pid")
        if not isinstance(pmt, PMTSection):
            raise TypeError(
                f"pmts entries must carry PMTSection, got {type(pmt).__name__}"
            )
        checked_pmts.append((pid, pmt))

    issues: list[ValidationIssue] = []

    # §8.1: PAT placement.
    if pat_pid != PAT_PID:
        issues.append(
            ValidationIssue(
                code=PAT_PID_INVALID,
                message=f"PAT is carried on PID {pat_pid:#06x}; the PAT "
                f"must be on PID {PAT_PID:#06x} (§8.1)",
                severity="error",
                field="pat_pid",
            )
        )

    # §8.2 precondition: the program_number mapping must be unambiguous.
    seen_numbers: dict[int, int] = {}
    for program in pat.programs:
        seen_numbers[program.program_number] = (
            seen_numbers.get(program.program_number, 0) + 1
        )
    for number in sorted(seen_numbers):
        count = seen_numbers[number]
        if count > 1:
            issues.append(
                ValidationIssue(
                    code=PAT_PROGRAM_NUMBER_INVALID,
                    message=f"program_number {number} appears {count} times "
                    "in the PAT program loop; the program to PMT PID "
                    "mapping must be unambiguous",
                    severity="error",
                    field="programs",
                )
            )

    # §8.2/§8.3/§8.7: PAT entry -> PMT associations.
    pmt_by_number: dict[int, int] = {}
    for pid, pmt in checked_pmts:
        pmt_by_number.setdefault(pmt.program_number, pid)
    for program in pat.programs:
        if program.program_number == 0:
            # network_PID entry: never a PMT pointer (§3), no diagnostic.
            continue
        if program.program_map_pid in (PAT_PID, NULL_PID):
            issues.append(
                ValidationIssue(
                    code=PAT_PMTPID_INVALID,
                    message=f"PAT program {program.program_number} maps to "
                    f"PID {program.program_map_pid:#06x}; the PAT fixed PID "
                    f"{PAT_PID:#06x} and the Null PID {NULL_PID:#06x} are "
                    "not usable PMT PIDs (§7)",
                    severity="error",
                    field="program_map_pid",
                )
            )
            continue
        found_pid = pmt_by_number.get(program.program_number)
        if found_pid is None:
            issues.append(
                ValidationIssue(
                    code=PAT_PMT_PROGRAM_MISMATCH,
                    message=f"no PMT found for program "
                    f"{program.program_number} (the PAT maps it to PID "
                    f"{program.program_map_pid:#06x}); no default PMT is "
                    "substituted (§8.7)",
                    severity="error",
                    field="program_map_pid",
                )
            )
        elif found_pid != program.program_map_pid:
            issues.append(
                ValidationIssue(
                    code=PAT_PMT_PROGRAM_MISMATCH,
                    message=f"PMT for program {program.program_number} was "
                    f"found on PID {found_pid:#06x} but the PAT maps that "
                    f"program to PID {program.program_map_pid:#06x}",
                    severity="error",
                    field="program_map_pid",
                )
            )

    # §8.3 (reverse)/§8.4/§8.5/§8.6: per-PMT checks.
    pat_numbers = set(seen_numbers)
    for pid, pmt in checked_pmts:
        if pmt.program_number not in pat_numbers:
            issues.append(
                ValidationIssue(
                    code=PAT_PMT_PROGRAM_MISMATCH,
                    message=f"PMT carried on PID {pid:#06x} claims "
                    f"program_number {pmt.program_number}, which has no "
                    "matching PAT entry (§8.7)",
                    severity="error",
                    field="program_number",
                )
            )
        if pmt.pcr_pid == NULL_PID:
            issues.append(
                ValidationIssue(
                    code=PMT_PID_INVALID,
                    message=f"PMT for program {pmt.program_number}: "
                    f"pcr_pid {NULL_PID:#06x} (Null PID) is rejected by "
                    "project rule; H.222.0 §2.4.4.8 permits 0x1FFF for "
                    "programs without PCR, so this is a DVB-Nexus "
                    "tightening, not a standard violation",
                    severity="error",
                    field="pcr_pid",
                )
            )
        elif pmt.pcr_pid == PAT_PID:
            issues.append(
                ValidationIssue(
                    code=PMT_PID_INVALID,
                    message=f"PMT for program {pmt.program_number}: "
                    f"pcr_pid {PAT_PID:#06x} is the PAT fixed PID and "
                    "cannot carry PCR",
                    severity="error",
                    field="pcr_pid",
                )
            )
        es_pids: dict[int, int] = {}
        for stream in pmt.streams:
            es_pids[stream.elementary_pid] = (
                es_pids.get(stream.elementary_pid, 0) + 1
            )
            if stream.elementary_pid in (PAT_PID, NULL_PID):
                issues.append(
                    ValidationIssue(
                        code=PMT_PID_INVALID,
                        message=f"PMT for program {pmt.program_number}: "
                        f"elementary_PID {stream.elementary_pid:#06x} must "
                        f"not be the PAT fixed PID ({PAT_PID:#06x}) or the "
                        f"Null PID ({NULL_PID:#06x})",
                        severity="error",
                        field="streams",
                    )
                )
        for es_pid in sorted(es_pids):
            count = es_pids[es_pid]
            if count > 1:
                issues.append(
                    ValidationIssue(
                        code=PMT_PID_INVALID,
                        message=f"PMT for program {pmt.program_number}: "
                        f"elementary_PID {es_pid:#06x} is used by {count} "
                        "ES entries; PIDs must be unique within a program "
                        "(§8.5)",
                        severity="error",
                        field="streams",
                    )
                )

    return issues
