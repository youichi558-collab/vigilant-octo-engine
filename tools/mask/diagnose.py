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
  Windows: 診断.bat に対象ファイルをドラッグ＆ドロップ（値は起動後に聞かれる）
  直接実行: python diagnose.py [対象ファイル] ["マスクされずに残った値"]
            引数を省略した場合は対話で入力を求める
"""

import html
import re
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mask_tool import (  # noqa: E402
    MaskRule,
    _iter_xlsx_all_texts,
    apply_rules,
    process_file,
    scan_file_candidates,
    tolerant_pattern,
)

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


def _scan_raw_parts(file_path: Path, target_norm: str):
    """ファイル内の全XMLパートを走査し、値を含むパートを役割ごとに返す。

    openpyxl等がセルとして読める範囲に関係なく、実際に格納されている全てを見る。
    ZIP形式でない場合は None を返す。
    """
    hits: dict[str, list[str]] = {}
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
                if target_norm and (
                    target_norm in _norm(html.unescape(content))
                    or target_norm in _norm(stripped)
                ):
                    hits.setdefault(_role_of(name), []).append(name)
    except zipfile.BadZipFile:
        return None
    return hits


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
    raw_hits = _scan_raw_parts(file_path, target_norm)
    if raw_hits is None:
        print("  (ZIP形式ではないため生データ検査をスキップ)")
        raw_hits = {}

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
    matched, unmatched = [], []
    for loc, text in visible_hits:
        (matched if apply_rules(text, [rule])[1] else unmatched).append((loc, text))

    print(f"  一致する  : {len(matched)}セル")
    print(f"  一致しない: {len(unmatched)}セル")
    if matched:
        sample = "、".join(loc for loc, _ in matched[:5])
        more = f" ほか{len(matched) - 5}セル" if len(matched) > 5 else ""
        print(f"    一致例: {sample}{more}")
    # 一致しないセルは原因究明に必要なので個別に出す（多い場合は先頭のみ）
    for loc, text in unmatched[:3]:
        print(f"\n  × {loc}")
        print(f"      セルの中身 : {text!r}")
        print(f"      指定した値 : {target!r}")
        print("      → 文字コードレベルの差異:")
        print("        [セルの中身]")
        print(_dump_chars(text))
        print("        [指定した値]")
        print(_dump_chars(target))
    if len(unmatched) > 3:
        print(f"\n  （ほか{len(unmatched) - 3}セルは省略）")

    # ---- 4. 自動検出パネルが実際に出す候補 ----
    # 【3】が全一致なのにマスクされない場合、チェックした候補の文字列が
    # ここで入力した値と違う（余計な文字を含む等）ことが原因になりうる。
    print("\n【4】自動検出パネルがこの値について出す候補")
    print("-" * 70)
    print("  ※ 画面でチェックするのは下記の文字列です。")
    print("     「この値そのもの」が候補に無い場合、チェックしても全部は消えません。")
    print()
    try:
        candidates = scan_file_candidates(file_path.name, file_path.read_bytes())
    except Exception as e:
        candidates = []
        print(f"  候補取得エラー: {e}")

    related = [c for c in candidates if target_norm and target_norm in _norm(c["value"])]
    exact = [c for c in related if _norm(c["value"]) == target_norm]

    if related:
        total = len(visible_hits)
        for c in related:
            c_rule = MaskRule(pattern=re.compile(tolerant_pattern(c["value"])), label="《テスト》")
            covered = sum(1 for _, text in visible_hits if apply_rules(text, [c_rule])[1])
            mark = "○" if covered == total else "△"
            print(f"  {mark} 候補 {c['value']!r} [{c['label']}]")
            print(f"      この候補をチェックした場合にマスクされるのは {covered}/{total} セル")
    else:
        print("  この値を含む候補は1件も出ていない")
        print("  → 画面でチェックしようがないため、マスクされない")

    if not exact:
        print()
        print(f"  ※ この値そのもの({target!r})は候補に出ていません。")

    # ---- 5. 実際にマスクを実行して生き残るセルを調べる ----
    # 【3】はセル単体にルールが一致するかを見るだけで、実際の書き込み処理
    # (mask_xlsx等)を通していない。「候補にも出るしルールも一致するのに
    # 一部しか消えない」場合、原因は照合ではなく書き込み側にあるため、
    # 本物のマスク処理を通した結果を直接確認する。
    print("\n【5】実際にマスクを実行した結果（本番と同じ処理を通す）")
    print("-" * 70)
    survivors = []
    raw_survivors = {}
    try:
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / ("masked" + file_path.suffix)
            process_file(file_path, out_path, [rule])
            for sheet, coord, text, is_formula in _iter_xlsx_all_texts(out_path):
                if target_norm and target_norm in _norm(text):
                    survivors.append((f"{sheet}!{coord}", text, is_formula))
            # セルとして読める範囲だけでなく、出力ファイル全体を再検査する
            # (テキストボックス等、セル以外に残っていても気付けるように)
            raw_survivors = _scan_raw_parts(out_path, target_norm)
    except Exception as e:
        print(f"  マスク実行エラー: {e}")
        survivors = None

    if survivors is None:
        pass
    elif not survivors and not raw_survivors:
        print(f"  ○ 残存なし（{len(visible_hits)}セルすべてマスクされた）")
    elif not survivors and raw_survivors:
        print("  × セルからは消えたが、ファイル内には残っている")
        for role, parts in raw_survivors.items():
            print(f"      {role}: {'、'.join(parts)}")
    else:
        print(f"  × {len(survivors)}セルが残った（対象 {len(visible_hits)}セル中）")
        print("     ↓ 残ったセルの中身。これが取りこぼしの実体です。")
        for loc, text, is_formula in survivors[:10]:
            kind = "数式セル" if is_formula else "通常セル"
            print(f"\n  × {loc}  [{kind}]")
            print(f"      中身: {text!r}")
            print("      文字構成:")
            print(_dump_chars(text[:40]))
        if len(survivors) > 10:
            print(f"\n  （ほか{len(survivors) - 10}セルは省略）")

    # ---- 判定 ----
    print("\n【判定】")
    print("-" * 70)
    if visible_hits and not unmatched:
        if exact:
            print("  セルからも読め、ルールも全セルに一致し、候補にもこの値が出ている。")
            print("  → 画面でこの候補にチェックを入れれば全てマスクされるはず。")
            print("     チェック漏れがないか確認してください。")
        else:
            print("  セルからも読め、ルールも全セルに一致するが、")
            print("  自動検出パネルにはこの値そのものが候補として出ていない。")
            print("  → チェックできる候補が部分的にしか一致しないため、取りこぼす。")
            print()
            print("  【今すぐの回避策】")
            print("    画面左の「置き換えリスト」の空欄に、この値を直接入力してから")
            print(f"    マスク実行してください（入力する値: {target}）。")
            print("    この経路なら全セルがマスクされます。")
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


def _prompt(message: str) -> str:
    """対話入力（バッチのset /pは文字コードの影響で入力待ちが素通りすることがあるため、
    入力の受け付けはPython側で行う）"""
    try:
        return input(message).strip().strip('"').strip("'")
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(1)


def main() -> None:
    args = sys.argv[1:]

    raw_path = args[0] if args else _prompt("調べたいファイルをここにドラッグして Enter: ")
    if not raw_path:
        sys.exit("ファイルが指定されていません。")
    file_path = Path(raw_path)
    if not file_path.exists():
        sys.exit(f"ファイルが見つかりません: {file_path}")

    target = args[1] if len(args) > 1 else _prompt("マスクされずに残った値を入力して Enter: ")
    if not target:
        sys.exit("値が入力されていません。")

    diagnose(file_path, target)
    print("=" * 70)
    print(" 上の内容をコピーして共有してください")
    print(" （値そのものが機密なら、その部分だけ伏せてください）")
    print("=" * 70)


if __name__ == "__main__":
    main()
