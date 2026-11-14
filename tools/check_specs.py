"""Spec 包一致性检查：front-matter / 包索引 / REGISTRY / 相对链接。

覆盖四类漂移（均为本仓库实际发生过或高 probable 的事故类）：

1. front-matter 校验：所有带 YAML front-matter 的规格/契约文件要求
   spec_id 全仓唯一、version 为 semver、status 在受控词表内；
   文件名 SPEC-<n>-*.md 的 n 必须与 spec_id 一致。
2. 正文状态行校验：无 front-matter 的文件中 `Version x.y.z | STATUS |`
   或 `Status: STATUS` 行的 STATUS 也须在词表内（存在才校验，不强制存在）。
3. ts-core 包一致性：SPEC-INDEX-TS-CORE 的表行 ↔ 实际文件互相覆盖，
   文件 front-matter 与包级 version/status 一致。
4. REGISTRY ↔ 模块文件：modules/ 下每个 SPEC-<n> 文件的 id 必须出现在
   REGISTRY 表行中；REGISTRY 行无对应文件视为合法占位（NOTE 不报错）。

用法（任意 CWD）：python -I tools/check_specs.py
退出码：0 = 通过；1 = 有 FAIL。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC_ROOT = ROOT / "docs" / "spec" / "DVB-Sandbox-Spec-v0.4-Complete"

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
STATUS_VOCAB = {
    "DRAFT",
    "DRAFT_FOR_REVIEW",
    "APPROVED",
    "MVP_BASELINE_APPROVED",
    "IMPLEMENTED",
    "DEPRECATED",
}

failures: list[str] = []
notes: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)


def note(msg: str) -> None:
    notes.append(msg)


def parse_front_matter(text: str) -> tuple[dict[str, str] | None, bool]:
    """解析平铺 key: value 的 YAML front-matter。

    返回 (data, closed)。无 front-matter 返回 (None, False)；
    有起始 --- 但无闭合 --- 返回 (data, False)。
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, False
    data: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return data, True
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*?)\s*$", line)
        if m and m.group(1) not in data:  # 多行 list 续行不匹配 key: value，忽略
            data[m.group(1)] = m.group(2)
    return data, False


def rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def check_front_matter(files: list[Path]) -> dict[Path, dict[str, str]]:
    seen_ids: dict[str, str] = {}
    front: dict[Path, dict[str, str]] = {}
    for p in sorted(files):
        text = p.read_text(encoding="utf-8-sig")
        data, closed = parse_front_matter(text)
        if data is None:
            continue
        r = rel(p)
        if not closed:
            fail(f"{r}: front-matter 未闭合")
            continue
        front[p] = data
        missing = [k for k in ("spec_id", "version", "status") if not data.get(k)]
        if missing:
            fail(f"{r}: front-matter 缺 {', '.join(missing)}")
            continue
        if not SEMVER.fullmatch(data["version"]):
            fail(f"{r}: version '{data['version']}' 不是 semver")
        if data["status"] not in STATUS_VOCAB:
            fail(f"{r}: status '{data['status']}' 不在词表 {sorted(STATUS_VOCAB)}")
        sid = data["spec_id"]
        if sid in seen_ids:
            fail(f"{r}: spec_id '{sid}' 重复（先前出现于 {seen_ids[sid]}）")
        else:
            seen_ids[sid] = r
        m = re.match(r"^SPEC-(\d+)", p.stem)
        if m and sid != f"SPEC-{m.group(1)}":
            fail(f"{r}: spec_id '{sid}' 与文件名编号不一致")
        # 无 front-matter 的文件靠正文状态行兜底校验
    return front


def check_body_status_lines(files: list[Path], covered: set[Path]) -> None:
    for p in sorted(files):
        if p in covered:
            continue
        text = p.read_text(encoding="utf-8-sig")
        r = rel(p)
        for m in re.finditer(r"^Version\s+\d+\.\d+\.\d+\s*\|\s*([A-Z_]+)\s*\|", text, re.M):
            if m.group(1) not in STATUS_VOCAB:
                fail(f"{r}: 正文状态行 status '{m.group(1)}' 不在词表")
        for m in re.finditer(r"^Status:\s*([A-Z_]+)", text, re.M):
            if m.group(1) not in STATUS_VOCAB:
                fail(f"{r}: 正文 Status 行 '{m.group(1)}' 不在词表")


def check_ts_core_index(front: dict[Path, dict[str, str]]) -> None:
    idx_path = SPEC_ROOT / "docs" / "modules" / "ts-core" / "SPEC-INDEX-TS-CORE.md"
    if not idx_path.exists():
        fail(f"{rel(idx_path)}: 不存在")
        return
    idx_dir = idx_path.parent
    text = idx_path.read_text(encoding="utf-8-sig")
    m_ver = re.search(r"\*\*Package version:\*\*\s*(\S+)", text)
    m_st = re.search(r"\*\*Status:\*\*\s*(\S+)", text)
    if not m_ver or not m_st:
        fail(f"{rel(idx_path)}: 缺 Package version / Status 包级头")
        return
    pkg_ver, pkg_st = m_ver.group(1), m_st.group(1)
    if not SEMVER.fullmatch(pkg_ver):
        fail(f"{rel(idx_path)}: 包版本 '{pkg_ver}' 不是 semver")
    if pkg_st not in STATUS_VOCAB:
        fail(f"{rel(idx_path)}: 包状态 '{pkg_st}' 不在词表")

    rows = re.findall(r"^\|\s*(SPEC-\d+)\s*\|\s*\[[^\]]+\]\(([^)]+)\)", text, re.M)
    row_ids = set()
    for sid, link in rows:
        row_ids.add(sid)
        target = idx_dir / link
        if not target.exists():
            fail(f"{rel(idx_path)}: 行 {sid} 链接目标不存在: {link}")
            continue
        data = front.get(target.resolve())
        if not data:
            fail(f"{rel(idx_path)}: 行 {sid} 指向的文件缺 front-matter: {link}")
            continue
        if data.get("spec_id") != sid:
            fail(f"{rel(target)}: spec_id '{data.get('spec_id')}' 与索引行 {sid} 不一致")
        if data.get("version") != pkg_ver:
            fail(f"{rel(target)}: version {data.get('version')} 与包版本 {pkg_ver} 不一致")
        if pkg_st == "MVP_BASELINE_APPROVED" and data.get("status") != "APPROVED":
            fail(
                f"{rel(target)}: 包状态 {pkg_st} 但文件 status 为 '{data.get('status')}'（应为 APPROVED）"
            )

    ts_dir = idx_dir
    for p in sorted(ts_dir.glob("SPEC-1*.md")):
        sid = re.match(r"^(SPEC-\d+)", p.stem).group(1)
        if sid not in row_ids:
            fail(f"{rel(p)}: 文件未收录于 {idx_path.name} 表")


def check_registry(front: dict[Path, dict[str, str]]) -> None:
    reg_path = SPEC_ROOT / "docs" / "modules" / "REGISTRY.md"
    if not reg_path.exists():
        fail(f"{rel(reg_path)}: 不存在")
        return
    text = reg_path.read_text(encoding="utf-8-sig")
    reg_ids = set(re.findall(r"^\|\s*(SPEC-\d+)\s*\|", text, re.M))
    module_files = [
        p
        for p in (SPEC_ROOT / "docs" / "modules").rglob("SPEC-*.md")
        if not p.name.startswith("SPEC-INDEX")
    ]
    for p in sorted(module_files):
        fid = re.match(r"^(SPEC-\d+)", p.stem).group(1)
        if fid not in reg_ids:
            fail(f"{rel(p)}: 文件编号 {fid} 未出现在 REGISTRY 表")
    for rid in sorted(reg_ids):
        matches = [p for p in module_files if p.stem == rid or p.stem.startswith(rid + "-")]
        if not matches:
            note(f"REGISTRY {rid}: 无对应文件（按 REGISTRY 说明视为待编写占位）")
            continue
        for p in matches:
            data = front.get(p)
            if data and data.get("spec_id") and data["spec_id"] != rid:
                fail(f"{rel(p)}: spec_id '{data['spec_id']}' 与 REGISTRY 行 {rid} 不一致")


def check_relative_links() -> None:
    files = list((ROOT / "docs" / "adr").glob("*.md"))
    files += [p for p in (ROOT / "docs").glob("*.md")]
    agents = ROOT / "AGENTS.md"
    if agents.exists():
        files.append(agents)
    for p in sorted(files):
        text = p.read_text(encoding="utf-8-sig")
        for m in re.finditer(r"\]\(([^)\s]+)\)", text):
            target = m.group(1).split("#", 1)[0]
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            resolved = (p.parent / target).resolve()
            if not resolved.exists():
                fail(f"{rel(p)}: 相对链接断链: {target}")


def main() -> int:
    if not SPEC_ROOT.exists():
        fail(f"spec 包根目录不存在: {rel(SPEC_ROOT)}")
    else:
        spec_files = [p for p in SPEC_ROOT.rglob("SPEC-*.md") if not p.name.startswith("SPEC-INDEX")]
        contract_files = list(SPEC_ROOT.rglob("*-INTEGRATION-CONTRACT.md"))
        front = check_front_matter(spec_files + contract_files)
        check_body_status_lines(spec_files + contract_files, set(front))
        check_ts_core_index(front)
        check_registry(front)
    check_relative_links()

    for n in notes:
        print(f"NOTE  {n}")
    for f in failures:
        print(f"FAIL  {f}")
    print(f"\n{len(failures)} failed, {len(notes)} notes")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
