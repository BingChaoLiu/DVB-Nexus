"""Phase 3 teaching-anchor acceptance — roadmap §4 领域 A 订正口径, asserted
on the SHIPPED artifacts (ticket #172 acceptance item ③).

The roadmap §4 A1/A2 anchors are the corrected teaching canon (⚠️ 订正
items).  This test pins every §4-assertable clause against the artifacts
that will carry the teaching (the Lab Pack v3 scenario documents) and
against the production constants the anchors name — the A1/A2 教学
锚点验收.  文案面 items that cannot be asserted mechanically (the roadmap
prose itself — NOT a shipped artifact) are honestly noted in the ticket
REPORT rather than fabricated here.

Anchors asserted (roadmap §4 领域 A verbatim clauses):

- A1 ①SCR 展开名 = Satellite Channel Router (EN 50494) — 且
  「Subscriber Channel Radio」不存在于任何产物文案；
- A1 ②冲突本质 = 同一 User Band 被两个接收端占用导致 SCR 堆叠信号互相
  干扰，不是 LNB 本振冲突（SC-10 hidden_reference_solution 文案 + E2E
  实测冲突对 face 在 test_e2e_phase3_state_lab）;
- A1 ③EN 50607（dCSS/Unicable II）扩展至最多 32 个 UB（生产常量
  MAX_UB_SLOT_BY_PROTOCOL 的 32-UB 位宽）；
- A2 ①高频段正常、切低频段时 BER 飙升的不对称症状（SC-11 文案 + E2E
  实测 850 MHz 错锁 face）；
- A2 ②LNB 供电/多路开关异常使低频段指令混入残留 22kHz，LNB 错误切入
  高频本振（SC-11 hidden_reference_solution 文案）；
- A2 ③训练目标 = 物理视图电压（13/18V）× 22kHz 组合逻辑排查（SC-11
  文案）；
- 850 MHz 不对称算术（SPEC-621 appendix A 尾段）：双本振差恰为
  850 MHz（10600 − 9750），E2E 错锁别名差同值；
- TS 101 964 引用落点：22kHz 物理层权威引用 = ETSI TS 101 964（免费
  normative）+ TI SLVA863，且产物**不编造** EN 50494/EN 50607 条款号
  （AC-623-05 缺口留档纪律）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

from simulation.state.unicable import (
    MAX_UB_SLOT_BY_PROTOCOL,
    UNICABLE_PROTOCOL_EN50494,
    UNICABLE_PROTOCOL_EN50607,
)

from tests._support.paths import REPO_ROOT

SCENARIO_DIR = REPO_ROOT / "scenarios"

SC10_PATH = SCENARIO_DIR / "SC-10-unicable_ub_conflict.json"
SC11_PATH = SCENARIO_DIR / "SC-11-tone_residue.json"


def _scenario(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _teaching_text(document: dict) -> str:
    """The shipped teaching copy of one scenario (title + objectives +
    hints + the hidden reference solution) — the artifacts the trainee
    actually reads."""
    parts = [document["title"]]
    parts.extend(document["objectives"])
    parts.extend(hint["content"] for hint in document["hints"])
    solution = document.get("hidden_reference_solution") or ""
    parts.append(solution)
    return "\n".join(parts)


class TestA1UnicableAnchors:
    """roadmap §4 A1 订正口径 — the SCR conflict canon."""

    def test_scr_expansion_name_is_satellite_channel_router(self):
        text = _teaching_text(_scenario(SC10_PATH))
        assert "Satellite Channel Router" in text
        # The ⚠️ 订正 negative face: wherever the WRONG expansion appears
        # in a shipped copy, it appears ONLY inside the correction's
        # explicit negation (非 "Subscriber Channel Radio") — never as an
        # un-negated claim.
        wrong = "Subscriber Channel Radio"
        for path in (SC10_PATH, SC11_PATH):
            shipped = _teaching_text(_scenario(path))
            start = 0
            while True:
                at = shipped.find(wrong, start)
                if at < 0:
                    break
                prefix = shipped[max(0, at - 4) : at].rstrip()
                assert prefix.endswith("非"), (
                    f"{path.name}: un-negated wrong SCR expansion at {at}"
                )
                start = at + len(wrong)

    def test_conflict_essence_is_scr_stacking_not_lnb_lo(self):
        text = _teaching_text(_scenario(SC10_PATH))
        # The corrected essence: SCR 堆叠层冲突, 与 LNB 本振无关.
        assert "SCR 堆叠" in text
        assert "不是 LNB 本振冲突" in text

    def test_en50607_extends_to_32_user_bands(self):
        # A1 ③: dCSS/Unicable II extends to AT MOST 32 UBs — the
        # production bit-width constant is the 32-slot space (0..31).
        assert MAX_UB_SLOT_BY_PROTOCOL[UNICABLE_PROTOCOL_EN50607] == 31
        assert MAX_UB_SLOT_BY_PROTOCOL[UNICABLE_PROTOCOL_EN50494] == 7


class TestA2ToneResidueAnchors:
    """roadmap §4 A2 订正口径 — the 22kHz residue canon."""

    def test_asymmetric_symptom_face_in_the_scenario_copy(self):
        document = _scenario(SC11_PATH)
        text = _teaching_text(document)
        # ① 高频段正常、切低频段时 BER 飙升 — the asymmetry is the title's
        # own claim and the objectives name it.
        assert "高频段正常" in document["title"]
        assert "不对称" in text
        assert "失锁或错锁" in text

    def test_residue_mechanism_copy(self):
        # ② 供电/多路开关异常 → 低频段指令混入残留 22kHz → 错误切入高频本振.
        text = _teaching_text(_scenario(SC11_PATH))
        assert "残留 22kHz" in text
        assert "高频本振" in text

    def test_training_goal_is_the_voltage_times_22kHz_combination(self):
        # ③ 物理视图电压（13/18V）× 22kHz 组合逻辑排查.
        text = _teaching_text(_scenario(SC11_PATH))
        assert "13/18V" in text
        assert "22kHz 组合逻辑排查" in text
        # The 14-state truth table is the named training artifact.
        assert "14 态真值表" in text


class TestAsymmetryArithmeticAndReferences:
    """850 MHz 不对称算术（SPEC-621 appendix A 尾段）+ 引用落点纪律."""

    def test_lo_arms_differ_by_exactly_850_mhz(self):
        document = _scenario(SC11_PATH)
        lnb0 = next(
            node["config"]
            for node in document["initial_topology"]["nodes"]
            if node["nodeId"] == "lnb-0"
        )
        lnb1 = next(
            node["config"]
            for node in document["initial_topology"]["nodes"]
            if node["nodeId"] == "lnb-1"
        )
        for config in (lnb0, lnb1):
            lo = config["lo_frequencies"]
            assert lo["high_khz"] - lo["low_khz"] == 850_000
            assert lo["high_khz"] == 10_600_000
            assert lo["low_khz"] == 9_750_000

    def test_22kHz_reference_lands_on_free_normative_sources(self):
        # The reference discipline: ETSI TS 101 964 (free normative) +
        # TI SLVA863 — NOT a fabricated Eutelsat entry point.
        text = _teaching_text(_scenario(SC11_PATH))
        assert "TS 101 964" in text
        assert "SLVA863" in text

    def test_no_fabricated_clause_numbers_for_the_paywalled_standards(self):
        # AC-623-05 缺口留档纪律: EN 50494:2007 / EN 50607:2015 are
        # paywalled — NO clause numbers may appear in the shipped copy
        # (the four-implementation consensus annotation is the citation).
        pattern = re.compile(r"EN\s*50(494|607)[^\n]{0,4}(§|clause|Section)\s*\d", re.IGNORECASE)
        for path in (SC10_PATH, SC11_PATH):
            document = _scenario(path)
            match = pattern.search(_teaching_text(document))
            assert match is None, f"{path.name}: fabricated clause number {match!r}"

    def test_850MHz_shift_is_teachingly_named_in_the_solution(self):
        # The number itself is part of the A2 canon (the alias arithmetic
        # the trainee derives); the shipped solution names it.
        text = _teaching_text(_scenario(SC11_PATH))
        assert "850 MHz" in text
