# Windows shell 注意事项（Git Bash + 原生 Windows Python）

本仓库的主要工作环境是 Windows + Git Bash（MSYS）+ 原生 Windows Python。以下坑位实际踩过，写下来避免复发。

## Python 与 MSYS 路径

- 原生 Windows Python **不理解 MSYS 的 `/tmp` 等路径**：`Path("/tmp/f")` 会被解析为当前盘根下的 `\tmp\f`，得到 `FileNotFoundError`。
- 临时文件要给 Python 用时，用 `cygpath` 转换并经**环境变量**传入（不要写死在脚本里）：

  ```bash
  OUT=/tmp/result.md
  OUT_W="$(cygpath -w "$OUT")" python -I - << 'EOF'
  import os
  from pathlib import Path
  p = Path(os.environ["OUT_W"])
  EOF
  ```

- **禁止** `python -I some_file << 'EOF'`：文件参数会被当作**脚本**执行，heredoc 进 stdin 被忽略——实际跑的 不是你想要的逻辑。stdin 脚本一律用 `python -I -`。
- 处理仓库外不可信数据时保持 `-I`（隔离模式，不加载脚本目录与当前目录代码）。

## 编码与显示

- 仓库文本统一 UTF-8；Python 读写一律显式 `encoding="utf-8"`（Windows 默认 cp936 会静默坏字）。读带 BOM 的文本用 `utf-8-sig`。
- CJK 文本经管道（`head` / `tail` / `grep` → 控制台）显示可能乱码——**显示不可信**：判断"文件或 issue 内容是否损坏"必须做字节级校验（读回后用 `in` 判定锚点），不要相信控制台渲染。

## gh CLI

- 多行 body 用 heredoc 写临时文件 + `--body-file`（操作配方见 [issue-tracker.md](issue-tracker.md)）。
