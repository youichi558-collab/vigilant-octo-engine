#!/usr/bin/env python3
"""
マスクツール: 取扱説明書等から客先名・設備番号等の機密情報を隠蔽する

対応形式:
  PDF       → 黒塗り（PyMuPDF による真のリダクション）
  DOCX      → ラベル置換（例: [客先名]）
  TXT/MD/その他 → ラベル置換

インストール:
  pip install -r requirements.txt

使い方:
  # 単一ファイル
  python mask_tool.py input.pdf --config mask_config.yaml
  python mask_tool.py input.docx --config mask_config.yaml

  # 出力先を明示
  python mask_tool.py input.pdf --config mask_config.yaml --output masked.pdf

  # フォルダ内の全ファイルを一括処理
  python mask_tool.py ./manual_draft/ --config mask_config.yaml

  # 出力サフィックスを変更（デフォルト: _masked）
  python mask_tool.py input.docx --config mask_config.yaml --suffix _公開版
"""

import argparse
import re
import shutil
import sys
from pathlib import Path
from typing import NamedTuple

try:
    import yaml
except ImportError:
    sys.exit("エラー: pip install pyyaml が必要です")


class MaskRule(NamedTuple):
    pattern: re.Pattern
    label: str


def load_rules(config_path: str) -> list[MaskRule]:
    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    rules = []
    for m in data.get("masks", []):
        label = m.get("label", "[MASKED]")
        if "pattern" in m:
            try:
                rules.append(MaskRule(pattern=re.compile(m["pattern"]), label=label))
            except re.error as e:
                print(f"警告: 正規表現エラー ({m['pattern']}): {e} — スキップします")
        elif "value" in m:
            rules.append(MaskRule(pattern=re.compile(re.escape(m["value"])), label=label))
        else:
            print(f"警告: 'value' または 'pattern' がないエントリをスキップ: {m}")
    return rules


def apply_rules(text: str, rules: list[MaskRule]) -> tuple[str, int]:
    count = 0
    for rule in rules:
        new_text, n = rule.pattern.subn(rule.label, text)
        count += n
        text = new_text
    return text, count


# ---------- テキストファイル ----------

def mask_text_file(input_path: Path, output_path: Path, rules: list[MaskRule]) -> int:
    try:
        text = input_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = input_path.read_text(encoding="cp932", errors="replace")
    new_text, count = apply_rules(text, rules)
    output_path.write_text(new_text, encoding="utf-8")
    return count


# ---------- PDF ----------

def extract_pdf_images(pdf_bytes: bytes) -> list[dict]:
    """PDF内の画像を抽出してbase64サムネイル付きで返す"""
    try:
        import fitz
    except ImportError:
        return []
    try:
        from PIL import Image as PilImage
        import io, base64
    except ImportError:
        return []

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    seen: set[int] = set()
    result = []

    for page in doc:
        for img in page.get_images():
            xref = img[0]
            if xref in seen:
                continue
            seen.add(xref)
            try:
                img_data = doc.extract_image(xref)
                pil = PilImage.open(io.BytesIO(img_data["image"]))
                pil.thumbnail((120, 120))
                buf = io.BytesIO()
                pil.save(buf, format="PNG")
                b64 = base64.b64encode(buf.getvalue()).decode()
                result.append({
                    "xref": xref,
                    "width": img_data["width"],
                    "height": img_data["height"],
                    "thumbnail": f"data:image/png;base64,{b64}",
                })
            except Exception:
                pass

    doc.close()
    return result


def extract_page_text_candidates(pdf_bytes: bytes, page_num: int = 0) -> list[dict]:
    """指定ページのテキストを行単位で抽出し、座標付きで返す（重複除去・短行除外）"""
    try:
        import fitz
    except ImportError:
        return []

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if page_num >= len(doc):
        doc.close()
        return []

    page = doc[page_num]
    data = page.get_text("dict")
    doc.close()

    seen: set[str] = set()
    results: list[dict] = []

    for block in data.get("blocks", []):
        if block.get("type") != 0:  # テキストブロック以外はスキップ
            continue
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line.get("spans", [])).strip()
            if len(text) < 2 or text in seen:
                continue
            seen.add(text)
            bbox = line["bbox"]  # (x0, y0, x1, y1)
            results.append({
                "text": text,
                "bbox": list(bbox),
                "page": page_num,
            })

    return results


def scan_pdf_candidates(pdf_bytes: bytes, extra_patterns: list[dict] | None = None) -> list[dict]:
    """PDFテキストからマスク候補を検出して返す"""
    try:
        import fitz
    except ImportError:
        return []

    # スキャン用パターン（会社名・住所は新規、その他は既存パターンから値を拾う）
    SCAN_PATTERNS = [
        ("会社名", r"(?:株式会社|有限会社|合同会社|一般社団法人|公益社団法人|特定非営利活動法人)[\w・\-－～（）()]{1,30}"),
        ("会社名", r"[\w・\-－～（）()]{2,30}(?:株式会社|有限会社|合同会社)"),
        ("住所",   r"(?:北海道|東京都|大阪府|京都府|神奈川県|埼玉県|千葉県|愛知県|福岡県|兵庫県"
                   r"|静岡県|茨城県|広島県|宮城県|新潟県|長野県|岐阜県|栃木県|群馬県|岡山県"
                   r"|三重県|熊本県|鹿児島県|山口県|愛媛県|長崎県|奈良県|青森県|岩手県|大分県"
                   r"|石川県|山形県|富山県|秋田県|香川県|和歌山県|山梨県|福島県|徳島県|高知県"
                   r"|島根県|宮崎県|鳥取県|福井県|佐賀県|沖縄県)"
                   r"[\S]{1,60}(?:市|区|町|村)[\S]{1,40}"),
        ("電話番号", r"0\d{1,4}[\-－]\d{1,4}[\-－]\d{4}"),
        ("携帯番号", r"0[789]0[\-－]\d{4}[\-－]\d{4}"),
        ("FAX番号",  r"FAX[：:\s]*0\d{1,4}[\-－]\d{1,4}[\-－]\d{4}"),
        ("メール",   r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"),
        ("郵便番号", r"〒?\d{3}[\-－]\d{4}"),
        ("IPアドレス", r"\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"),
    ]
    # 呼び出し元から追加パターンを受け取る場合
    for ep in (extra_patterns or []):
        SCAN_PATTERNS.append((ep.get("label", "その他"), ep["pattern"]))

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    full_text = "\n".join(page.get_text() for page in doc)
    doc.close()

    seen: set[str] = set()
    results: list[dict] = []
    for label, pat in SCAN_PATTERNS:
        try:
            for m in re.finditer(pat, full_text):
                val = m.group().strip()
                if val and val not in seen:
                    seen.add(val)
                    results.append({"value": val, "label": label})
        except re.error:
            pass

    return results


def render_pdf_pages(pdf_bytes: bytes, max_pages: int = 10, scale: float = 1.5, start_page: int = 0) -> list[dict]:
    """PDF各ページをPNG画像としてレンダリングして返す"""
    try:
        import fitz
        import base64
    except ImportError:
        return []

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    mat = fitz.Matrix(scale, scale)
    pages = []

    end = min(start_page + max_pages, len(doc))
    for i in range(start_page, end):
        page = doc[i]
        pix = page.get_pixmap(matrix=mat)
        b64 = base64.b64encode(pix.tobytes("png")).decode()
        pages.append({
            "page": i,
            "pdf_width": page.rect.width,
            "pdf_height": page.rect.height,
            "image": f"data:image/png;base64,{b64}",
        })

    doc.close()
    return pages


def _norm_char(c: str) -> str:
    """照合用の文字正規化: 全角/半角の差・ハイフン類の字種差を吸収する"""
    import unicodedata
    c = unicodedata.normalize("NFKC", c)
    # ハイフン・ダッシュ類はすべて '-' に寄せる
    return "".join("-" if ch in "‐‑‒–—―−ー－" else ch for ch in c)


def _redact_text_occurrences(page, targets: list[str]) -> int:
    """ページ内の全文字を空白無視で連結し、対象文字列に一致する箇所を黒塗りする。

    - テキストが複数のオブジェクトに分割されていても(例: '5'+'ABC-123'+'C')全体をカバー
    - 全角/半角・ハイフン字種の違いを正規化して照合
    - 一致部分の前後にスペースなしで密着している文字(枝番・改訂記号など)も塗り広げる
    - 一致文字がその行の過半を占める場合は行全体を黒塗り
      (図面欄のように1文字ずつ間隔をあけて配置され、シート番号・改訂記号が
       スペースを挟んで同じ欄に入っているケースをカバーする)
    """
    import fitz

    def norm_str(s: str) -> str:
        return "".join(_norm_char(c) for c in s if not c.isspace())

    target_norms = [norm_str(t) for t in targets if norm_str(t)]
    if not target_norms:
        return 0

    # sort=True で視覚的な並び順(上→下、左→右)に文字を取得する
    # スペースは「区切りマーカー」として保持する(塗り広げの停止条件に使う)
    items: list[tuple[str, "fitz.Rect | None", int]] = []  # (char, rect, line_id)
    line_bboxes: list["fitz.Rect"] = []
    line_char_counts: list[int] = []  # 行ごとの非スペース文字数
    for block in page.get_text("rawdict", sort=True).get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            line_id = len(line_bboxes)
            line_bboxes.append(fitz.Rect(line["bbox"]))
            n_chars = 0
            for span in line.get("spans", []):
                for ch in span.get("chars", []):
                    c = ch.get("c", "")
                    if not c:
                        continue
                    if c.isspace():
                        items.append((" ", None, line_id))
                    else:
                        items.append((c, fitz.Rect(ch["bbox"]), line_id))
                        n_chars += 1
            line_char_counts.append(n_chars)
            items.append((" ", None, line_id))  # 行末も区切り扱い

    # 正規化ストリームと、各位置→itemsインデックスの対応表を作る
    stream_chars: list[str] = []
    stream_map: list[int] = []
    for i, (c, rect, _) in enumerate(items):
        if rect is None:
            continue
        for nc in _norm_char(c):
            stream_chars.append(nc)
            stream_map.append(i)
    stream = "".join(stream_chars)

    def _adjacent(a, b):  # aがbの左隣か
        h = max(a.height, b.height)
        same_row = abs((a.y0 + a.y1) - (b.y0 + b.y1)) / 2 < h * 0.7
        gap = b.x0 - a.x1
        return same_row and -h * 0.5 < gap < h * 0.35

    count = 0
    for tn in target_norms:
        start = 0
        while True:
            idx = stream.find(tn, start)
            if idx < 0:
                break
            lo = stream_map[idx]
            hi = stream_map[idx + len(tn) - 1]

            # 前後に密着している文字まで塗り広げる
            # (スペースで停止。テキストオブジェクトの境界は幾何的な隣接判定で越える)
            while lo - 1 >= 0 and items[lo - 1][1] is not None and _adjacent(items[lo - 1][1], items[lo][1]):
                lo -= 1
            while hi + 1 < len(items) and items[hi + 1][1] is not None and _adjacent(items[hi][1], items[hi + 1][1]):
                hi += 1

            # 行ごとの一致文字数を数える
            matched_per_line: dict[int, int] = {}
            for i in range(lo, hi + 1):
                if items[i][1] is not None:
                    matched_per_line[items[i][2]] = matched_per_line.get(items[i][2], 0) + 1

            covered_lines: set[int] = set()
            char_rects: list["fitz.Rect"] = []
            for line_id, n_matched in matched_per_line.items():
                if line_char_counts[line_id] > 0 and n_matched / line_char_counts[line_id] >= 0.5:
                    # 行の過半が一致 → 行全体(欄全体)を黒塗り
                    covered_lines.add(line_id)
                else:
                    # 文中の一部 → 一致した文字だけ黒塗り
                    char_rects.extend(items[i][1] for i in range(lo, hi + 1)
                                      if items[i][1] is not None and items[i][2] == line_id)

            # 同じ段にスペースを挟んで並ぶ短い断片行(シート番号・改訂記号など)まで塗り広げる
            # 長いラベル行(Drawing No.等)は文字数条件で除外される
            if covered_lines:
                changed = True
                while changed:
                    changed = False
                    for lid, lb in enumerate(line_bboxes):
                        if lid in covered_lines or line_char_counts[lid] == 0 or line_char_counts[lid] > 3:
                            continue
                        for cid in covered_lines:
                            cb = line_bboxes[cid]
                            h = max(lb.height, cb.height)
                            same_row = min(lb.y1, cb.y1) - max(lb.y0, cb.y0) > h * 0.5
                            gap = max(lb.x0, cb.x0) - min(lb.x1, cb.x1)
                            if same_row and gap < h * 2.0:
                                covered_lines.add(lid)
                                changed = True
                                break

            for line_id in covered_lines:
                page.add_redact_annot(line_bboxes[line_id] + (-1, -1, 1, 1), fill=(0, 0, 0))
                count += 1

            if char_rects:
                cur = fitz.Rect(char_rects[0])
                for r in char_rects[1:]:
                    same_row = abs((r.y0 + r.y1) - (cur.y0 + cur.y1)) / 2 < max(r.height, cur.height) * 0.7
                    if same_row:
                        cur |= r
                    else:
                        page.add_redact_annot(cur + (-1, -1, 1, 1), fill=(0, 0, 0))
                        count += 1
                        cur = fitz.Rect(r)
                page.add_redact_annot(cur + (-1, -1, 1, 1), fill=(0, 0, 0))
                count += 1

            start = idx + 1

    return count


def mask_pdf(
    input_path: Path,
    output_path: Path,
    rules: list[MaskRule],
    image_xrefs: list[int] | None = None,
    regions: list[dict] | None = None,
    line_texts: list[str] | None = None,
) -> int:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        sys.exit("エラー: pip install pymupdf が必要です")

    doc = fitz.open(str(input_path))
    total_pages = len(doc)
    total = 0
    xref_set = set(image_xrefs or [])

    # 範囲指定黒塗り: allPages=true の場合は全ページに展開
    region_map: dict[int, list] = {}
    for r in (regions or []):
        targets = range(total_pages) if r.get("allPages") else [int(r["page"])]
        for pg in targets:
            rect = fitz.Rect(r["x0"], r["y0"], r["x1"], r["y1"])
            region_map.setdefault(pg, []).append(rect)

    for i, page in enumerate(doc):
        # テキスト黒塗り
        page_text = page.get_text()
        matched_strings: set[str] = set()
        for rule in rules:
            for m in rule.pattern.finditer(page_text):
                matched_strings.add(m.group())
        for s in matched_strings:
            for rect in page.search_for(s):
                page.add_redact_annot(rect, fill=(0, 0, 0))
                total += 1

        # 画像黒塗り
        for img in page.get_images():
            xref = img[0]
            if xref in xref_set:
                try:
                    bbox = page.get_image_bbox(img)
                    page.add_redact_annot(bbox, fill=(0, 0, 0))
                    total += 1
                except Exception:
                    pass

        # 範囲指定黒塗り
        for rect in region_map.get(i, []):
            page.add_redact_annot(rect, fill=(0, 0, 0))
            total += 1

        # テキスト候補: 文字単位で照合して黒塗り
        # （番号が複数のテキストオブジェクトに分割されている場合や
        #   スペース有無の違いがあっても、文字列全体をカバーする）
        if line_texts:
            total += _redact_text_occurrences(page, line_texts)

        # 画像・ベクターグラフィックにも黒塗りを適用
        try:
            page.apply_redactions(
                images=fitz.PDF_REDACT_IMAGE_PIXELS,
                graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
            )
        except TypeError:
            page.apply_redactions()

    doc.save(str(output_path), garbage=4, deflate=True)
    doc.close()
    return total


# ---------- DOCX ----------

def _process_paragraphs(paragraphs, rules: list[MaskRule]) -> int:
    count = 0
    for para in paragraphs:
        full = para.text
        if not full.strip():
            continue
        new_full, n = apply_rules(full, rules)
        if n == 0:
            continue
        count += n
        runs = para.runs
        if not runs:
            continue
        # runs を先頭にまとめて置換（段落内インライン書式は先頭runの書式を引き継ぐ）
        runs[0].text = new_full
        for run in runs[1:]:
            run.text = ""
    return count


def mask_docx(input_path: Path, output_path: Path, rules: list[MaskRule]) -> int:
    try:
        from docx import Document
    except ImportError:
        sys.exit("エラー: pip install python-docx が必要です")

    shutil.copy2(input_path, output_path)
    doc = Document(str(output_path))
    total = 0

    # 本文
    total += _process_paragraphs(doc.paragraphs, rules)

    # テーブル（ネスト対応）
    def process_table(table):
        nonlocal total
        for row in table.rows:
            for cell in row.cells:
                total += _process_paragraphs(cell.paragraphs, rules)
                for nested in cell.tables:
                    process_table(nested)

    for table in doc.tables:
        process_table(table)

    # ヘッダー・フッター
    for section in doc.sections:
        total += _process_paragraphs(section.header.paragraphs, rules)
        total += _process_paragraphs(section.footer.paragraphs, rules)
        # 偶数・奇数ページのヘッダー/フッター
        for hdr in (section.even_page_header, section.first_page_header):
            total += _process_paragraphs(hdr.paragraphs, rules)
        for ftr in (section.even_page_footer, section.first_page_footer):
            total += _process_paragraphs(ftr.paragraphs, rules)

    doc.save(str(output_path))
    return total


# ---------- ディスパッチ ----------

TEXT_SUFFIXES = {".txt", ".md", ".csv", ".log", ".ini", ".json", ".xml", ".html", ".htm"}

def process_file(input_path: Path, output_path: Path, rules: list[MaskRule], image_xrefs: list[int] | None = None, regions: list[dict] | None = None, line_texts: list[str] | None = None):
    suffix = input_path.suffix.lower()
    if suffix == ".pdf":
        count = mask_pdf(input_path, output_path, rules, image_xrefs, regions, line_texts)
        print(f"  [PDF ]  {count:4d}箇所 黒塗り  → {output_path.name}")
    elif suffix == ".docx":
        count = mask_docx(input_path, output_path, rules)
        print(f"  [DOCX]  {count:4d}箇所 ラベル置換 → {output_path.name}")
    elif suffix in TEXT_SUFFIXES or suffix == "":
        count = mask_text_file(input_path, output_path, rules)
        print(f"  [TEXT]  {count:4d}箇所 ラベル置換 → {output_path.name}")
    else:
        # 非対応形式はコピーのみ
        shutil.copy2(input_path, output_path)
        print(f"  [SKIP]  非対応形式のためコピーのみ → {output_path.name}")


# ---------- メイン ----------

def main():
    parser = argparse.ArgumentParser(
        description="マスクツール: 機密情報を隠蔽して共有可能なファイルを生成する",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", help="入力ファイルまたはフォルダ")
    parser.add_argument("--config", required=True, help="マスク設定ファイル (YAML)")
    parser.add_argument("--output", help="出力先ファイル/フォルダ（省略時は自動命名）")
    parser.add_argument(
        "--suffix", default="_masked",
        help="出力ファイルに付加するサフィックス（デフォルト: _masked）"
    )
    args = parser.parse_args()

    rules = load_rules(args.config)
    if not rules:
        print("警告: マスクルールが0件です。mask_config.yaml を確認してください。")
        return

    print(f"マスクルール: {len(rules)}件 読み込み完了")

    input_path = Path(args.input)
    if not input_path.exists():
        sys.exit(f"エラー: 入力パスが見つかりません: {input_path}")

    if input_path.is_dir():
        output_dir = Path(args.output) if args.output else input_path.parent / (input_path.name + args.suffix)
        output_dir.mkdir(parents=True, exist_ok=True)
        files = sorted(f for f in input_path.rglob("*") if f.is_file())
        print(f"フォルダ処理: {len(files)}ファイル → {output_dir}/")
        for f in files:
            rel = f.relative_to(input_path)
            out = output_dir / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            process_file(f, out, rules)
    else:
        if args.output:
            output_path = Path(args.output)
        else:
            output_path = input_path.parent / (input_path.stem + args.suffix + input_path.suffix)
        process_file(input_path, output_path, rules)

    print("完了")


if __name__ == "__main__":
    main()
