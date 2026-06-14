#!/usr/bin/env python3
"""
カタログPDFから表を抽出し、JSON/CSVとしてリポジトリに保存する。

使用方法:
    python scripts/convert_catalog.py <pdf_path> <pages> <output_name> [オプション]

引数:
    pdf_path     ローカルPDFパス (例: /tmp/三菱ブレーカー総合カタログ.pdf)
    pages        ページ範囲 (例: 145-186 または 145,150,160-170)
    output_name  出力フォルダ名 (例: mitsubishi_breaker)

オプション:
    --flavor     camelotの読取方式: lattice(罫線あり) / stream(罫線なし) [デフォルト: lattice]
    --fallback   camelot失敗時にtabulaへフォールバック [デフォルト: 有効]

出力先:
    database/parts_master/catalog_tables/<output_name>/
        tables.json         全テーブルのメタデータと内容
        table_NNN_pPP.csv   テーブルごとの個別CSV

例:
    python scripts/convert_catalog.py \\
        /tmp/三菱ブレーカー総合カタログ.pdf \\
        145-186 \\
        mitsubishi_breaker_selection
"""

import sys
import json
import argparse
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent
OUTPUT_BASE = REPO_ROOT / "database" / "parts_master" / "catalog_tables"


def parse_args():
    parser = argparse.ArgumentParser(
        description="カタログPDFから表を抽出してJSON/CSVに変換する"
    )
    parser.add_argument("pdf_path", help="ローカルPDFファイルパス")
    parser.add_argument("pages", help="ページ範囲 (例: 145-186 または all)")
    parser.add_argument("output_name", help="出力フォルダ名")
    parser.add_argument(
        "--flavor",
        choices=["lattice", "stream"],
        default="lattice",
        help="camelot読取方式: lattice=罫線あり(デフォルト), stream=罫線なし",
    )
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="camelot失敗時のtabulaフォールバックを無効化",
    )
    return parser.parse_args()


def extract_with_camelot(pdf_path: str, pages: str, flavor: str) -> list[dict]:
    import camelot

    print(f"[camelot/{flavor}] {pdf_path} ページ:{pages} を読み込み中...")
    tables = camelot.read_pdf(pdf_path, pages=pages, flavor=flavor)
    print(f"  → {len(tables)} テーブル検出")

    results = []
    for i, table in enumerate(tables):
        df = table.df
        results.append(
            {
                "table_index": i,
                "page": table.page,
                "accuracy": round(table.accuracy, 1),
                "rows": len(df),
                "cols": len(df.columns),
                "data": df.values.tolist(),
            }
        )
    return results


def extract_with_tabula(pdf_path: str, pages: str) -> list[dict]:
    import tabula

    # tabula は pages指定が "145-186" 形式そのまま使える
    print(f"[tabula] {pdf_path} ページ:{pages} を読み込み中...")
    dfs = tabula.read_pdf(pdf_path, pages=pages, multiple_tables=True, silent=True)
    print(f"  → {len(dfs)} テーブル検出")

    results = []
    for i, df in enumerate(dfs):
        results.append(
            {
                "table_index": i,
                "page": None,   # tabulaはページ番号を個別に返さない
                "accuracy": None,
                "rows": len(df),
                "cols": len(df.columns),
                "data": df.fillna("").astype(str).values.tolist(),
            }
        )
    return results


def save_outputs(tables: list[dict], output_dir: Path, pdf_path: str, pages: str, extractor: str):
    output_dir.mkdir(parents=True, exist_ok=True)

    # 個別CSV
    for t in tables:
        page_label = f"p{t['page']}" if t["page"] else f"idx{t['table_index']}"
        csv_path = output_dir / f"table_{t['table_index']:03d}_{page_label}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            import csv
            writer = csv.writer(f)
            writer.writerows(t["data"])
        acc = f"{t['accuracy']}%" if t["accuracy"] is not None else "N/A"
        print(f"  表{t['table_index']:03d}: {t['rows']}行 × {t['cols']}列, 精度:{acc} → {csv_path.name}")

    # 統合JSON
    json_path = output_dir / "tables.json"
    payload = {
        "source_pdf": str(pdf_path),
        "pages": pages,
        "extractor": extractor,
        "extracted_at": datetime.now().isoformat(timespec="seconds"),
        "total_tables": len(tables),
        "tables": tables,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"\n完了: {len(tables)} テーブルを保存")
    print(f"出力先: {output_dir}")
    print(f"  統合JSON : {json_path}")


def main():
    args = parse_args()
    pdf_path = args.pdf_path
    pages = args.pages
    output_name = args.output_name
    output_dir = OUTPUT_BASE / output_name

    if not Path(pdf_path).exists():
        print(f"ERROR: PDFが見つかりません: {pdf_path}")
        sys.exit(1)

    extractor_used = "camelot"
    tables = []

    # camelotで試みる
    try:
        tables = extract_with_camelot(pdf_path, pages, args.flavor)
    except Exception as e:
        print(f"[camelot] エラー: {e}")
        if args.no_fallback:
            print("フォールバック無効のため終了します。")
            sys.exit(1)
        print("tabulaにフォールバックします...")

    # camelotが0件 or 失敗時にtabulaを試みる
    if not tables and not args.no_fallback:
        try:
            tables = extract_with_tabula(pdf_path, pages)
            extractor_used = "tabula"
        except Exception as e:
            print(f"[tabula] エラー: {e}")
            print("両エクストラクタが失敗しました。")
            sys.exit(1)

    if not tables:
        print("テーブルが1件も検出されませんでした。")
        print("ヒント: --flavor stream を試してください (罫線なしPDF向け)。")
        sys.exit(1)

    save_outputs(tables, output_dir, pdf_path, pages, extractor_used)


if __name__ == "__main__":
    main()
