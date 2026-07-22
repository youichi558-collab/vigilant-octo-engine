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


def mask_pdf(
    input_path: Path,
    output_path: Path,
    rules: list[MaskRule],
    image_xrefs: list[int] | None = None,
    regions: list[dict] | None = None,
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

        page.apply_redactions()

    doc.save(str(output_path))
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

def process_file(input_path: Path, output_path: Path, rules: list[MaskRule], image_xrefs: list[int] | None = None, regions: list[dict] | None = None):
    suffix = input_path.suffix.lower()
    if suffix == ".pdf":
        count = mask_pdf(input_path, output_path, rules, image_xrefs, regions)
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
