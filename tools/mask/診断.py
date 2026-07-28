#!/usr/bin/env python3
"""
マスク診断ツール: 「マスクされずに残る値」がファイルのどこに、どういう形で
入っているのかを特定する。

マスクツール本体が値を見つけられない原因は、値そのものではなく「どこに
格納されているか」であることが多い(テキストボックス・ヘッダー・コメント・
数式・特殊文字の混入など)。このツールはファイルを2つの視点で調べる:

  1. openpyxl から見えるセル(= マスクツール本体が処理できる範囲)
  2. ファイルの生XML全体(= 見え方に関係なく実際に格納されている全て)

1に無く2にある場合、その値はマスクツールから原理的に見えていないため、
本体側の対応が必要になる(どこに入っていたかがこのツールで判明する)。

ファイルはPC外に送信されない。

使い方:
  python 診断.py 対象ファイル.xlsx "マスクされずに残った値"

  例:
  python 診断.py 仕様書.xlsx "鈴木一郎"
"""

import html
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mask_tool import MaskRule, apply_rules, tolerant_pattern  # noqa: E402

# XLSXのZIP内パスと、その中身が何を表すかの対応
# (マスクツール本体がセルとして読めるのは worksheets のみ)
_PART_ROLES = [
    ("xl/worksheets/", "セル(通常マスク対象)"),
    ("xl/sharedStrings.xml", "共有文字列(セルの実体。通常マスク対象)"),
    ("xl/drawings/", "テキストボックス・図形"),
    ("xl/charts/", "グラフのタイトル・ラベル"),
    ("xl/comments", "セルのコメント/メモ"),
    ("xl/threadedComments/", "スレッドコメント"),
    ("xl/headerFooter", "ヘッダー/フッター"),
    ("docProps/", "ファイルのプロパティ(作成者など)"),
    ("xl/workbook.xml", "シート名・定義名"),
]


def _role_of(part_name: str) -> str:
    for prefix, role in _PART_ROLES:
        if part_name.startswith(prefix):
            return role
    return "その他"


def _dump_chars(s: str) -> str:
    """文字ごとに Unicode 名を出す(目に見えない差異を暴くため)"""
    out = []
    for ch in s:
        if ch == "\n":
            name = "改行(セル内改行 Alt+Enter)"
        elif ch == "\t":
            name = "タブ"
        else:
            try:
                name = unicodedata.name(ch)
            except ValueError:
                name = "?"
        out.append(f"    {ch!r:8} U+{ord(ch):04X}  {name}")
    return "\n".join(out)


def _norm(s: str) -> str:
    """比較用にゆるく正規化(全角半角・空白差を吸収)"""
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"\s+", "", s)


def diagnose(file_path: Path, target: str) -> None:
    print("=" * 70)
    print(f"対象ファイル: {file_path.name}")
    print(f"探す値      : {target!r}")
    print("=" * 70)

    target_norm = _norm(target)

    # ---- 1. マスクツール本体から見えるセル ----
    print("\n【1】マスクツールがセルとして読める範囲での検出")
    print("-" * 70)
    visible_hits = []
    if file_path.suffix.lower() == ".xlsx":
        try:
            from mask_tool import _iter_xlsx_all_texts
            for sheet, coord, text, is_formula in _iter_xlsx_all_texts(file_path):
                if target_norm and target_norm in _norm(text):
                    visible_hits.append((f"{sheet}!{coord}" + ("(数式)" if is_formula else ""), text))
        except Exception as e:
            print(f"  読み取りエラー: {e}")

    if visible_hits:
        for loc, text in visible_hits:
            print(f"  ○ {loc}")
            print(f"      セルの中身: {text!r}")
    else:
        print("  × セルとしては1件も見つからない")
        print("    → マスクツールからこの値は見えていない(【2】でどこにあるか特定する)")

    # ---- 2. ファイルの生XML全体 ----
    print("\n【2】ファイル内部(生データ)での検出 ... 実際にどこに格納されているか")
    print("-" * 70)
    raw_hits = {}
    try:
        with zipfile.ZipFile(file_path) as z:
            for name in z.namelist():
                if not name.endswith((".xml", ".rels")):
                    continue
                try:
                    content = z.read(name).decode("utf-8", errors="ignore")
                except Exception:
                    continue
                # XMLタグを除去し、文字参照(&#37428; など)を実文字に戻してから比較
                # (Excelは日本語を数値文字参照で保存することがあり、生文字列のままでは一致しない)
                stripped = html.unescape(re.sub(r"<[^>]+>", "", content))
                if target_norm and (target_norm in _norm(html.unescape(content)) or target_norm in _norm(stripped)):
                    raw_hits.setdefault(_role_of(name), []).append(name)
    except zipfile.BadZipFile:
        print("  (ZIP形式ではないため生データ検査をスキップ)")

    if raw_hits:
        for role, parts in raw_hits.items():
            print(f"  ○ {role}")
            for p in parts:
                print(f"      {p}")
    else:
        print("  × ファイル内部にも見つからない")
        print("    → 値の指定自体がファイル内の表記と違う可能性(【3】を確認)")

    # ---- 3. マスクルールが実際に一致するかの検証 ----
    print("\n【3】マスクルールがこの値に一致するかの検証")
    print("-" * 70)
    rule = MaskRule(pattern=re.compile(tolerant_pattern(target)), label="《テスト》")
    for loc, text in visible_hits:
        masked, n = apply_rules(text, [rule])
        mark = "○" if n else "×"
        print(f"  {mark} {loc}: {n}箇所一致")
        if not n:
            print(f"      セルの中身 : {text!r}")
            print(f"      指定した値 : {target!r}")
            print("      → 文字コードレベルの差異:")
            print("        [セルの中身]")
            print(_dump_chars(text))
            print("        [指定した値]")
            print(_dump_chars(target))

    # ---- 判定 ----
    print("\n【判定】")
    print("-" * 70)
    if visible_hits and all(apply_rules(t, [rule])[1] for _, t in visible_hits):
        print("  セルからも読めており、ルールも一致する。")
        print("  → この値はマスクできるはず。マスク実行時に候補として")
        print("     チェックが入っていたか確認してください。")
    elif visible_hits:
        print("  セルからは読めるが、ルールが一致しない。")
        print("  → 【3】の文字コード差異が原因。この出力を共有してください。")
    elif raw_hits:
        roles = "、".join(raw_hits.keys())
        print(f"  セルとしては読めないが、ファイル内の「{roles}」に存在する。")
        print("  → マスクツールが未対応の格納場所。この出力を共有してください。")
    else:
        print("  ファイル内のどこにも見つからない。")
        print("  → 指定した値の表記を、ファイル上の表示と突き合わせてください。")
    print()


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    file_path = Path(sys.argv[1])
    if not file_path.exists():
        sys.exit(f"エラー: ファイルが見つかりません: {file_path}")
    diagnose(file_path, sys.argv[2])


if __name__ == "__main__":
    main()
