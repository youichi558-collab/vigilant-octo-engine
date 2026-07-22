#!/usr/bin/env python3
"""
マスクツール Web UI

起動:
  cd tools/mask
  python app.py
  → ブラウザで http://localhost:5000 を開く
"""

import io
import json
import os
import re
import tempfile
from pathlib import Path

import yaml
from flask import Flask, jsonify, render_template, request, send_file

from mask_tool import MaskRule, audit_pdf, extract_page_text_candidates, extract_pdf_images, process_file, render_pdf_pages, scan_pdf_candidates

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100MB

CONFIG_PATH = Path(__file__).parent / "mask_config.yaml"


@app.after_request
def no_cache(response):
    """ブラウザが古いUIをキャッシュして修正が反映されない事故を防ぐ"""
    response.headers["Cache-Control"] = "no-store"
    return response


def parse_config(config_path: Path) -> dict:
    """YAMLを読み込み、value規則とpattern規則に分けて返す"""
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    value_rules = []
    pattern_rules = []
    for m in data.get("masks", []):
        label = m.get("label", "《MASKED》")
        if "value" in m:
            value_rules.append({"placeholder": m["value"], "label": label, "value": ""})
        elif "pattern" in m:
            pattern_rules.append({"pattern": m["pattern"], "label": label})
    return {"value_rules": value_rules, "pattern_rules": pattern_rules}


def build_rules(form: dict, value_rules: list, pattern_rules: list) -> list[MaskRule]:
    rules = []
    for i, rule in enumerate(value_rules):
        val = form.get(f"val_{i}", "").strip()
        if val:
            rules.append(MaskRule(pattern=re.compile(re.escape(val)), label=rule["label"]))
    for i, rule in enumerate(pattern_rules):
        if form.get(f"pat_{i}") == "on":
            try:
                rules.append(MaskRule(pattern=re.compile(rule["pattern"]), label=rule["label"]))
            except re.error:
                pass
    return rules


@app.route("/")
def index():
    config = parse_config(CONFIG_PATH)
    return render_template("index.html", **config)


@app.route("/render_pages", methods=["POST"])
def render_pages():
    file = request.files.get("file")
    if not file:
        return jsonify({"pages": [], "total": 0})
    pdf_bytes = file.read()

    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total = len(doc)
        doc.close()
    except Exception:
        total = 0

    page_num = int(request.form.get("page_num", 1)) - 1  # 0-indexed
    page_num = max(0, min(page_num, total - 1))

    pages = render_pdf_pages(pdf_bytes, max_pages=1, start_page=page_num)
    text_lines = extract_page_text_candidates(pdf_bytes, page_num)
    return jsonify({"pages": pages, "total": total, "text_lines": text_lines})


@app.route("/scan_candidates", methods=["POST"])
def scan_candidates():
    file = request.files.get("file")
    if not file:
        return jsonify({"candidates": []})
    pdf_bytes = file.read()
    candidates = scan_pdf_candidates(pdf_bytes)
    return jsonify({"candidates": candidates})


@app.route("/extract_images", methods=["POST"])
def extract_images():
    file = request.files.get("file")
    if not file:
        return jsonify({"images": []})
    pdf_bytes = file.read()
    images = extract_pdf_images(pdf_bytes)
    return jsonify({"images": images})


@app.route("/process", methods=["POST"])
def process():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "ファイルが選択されていません"}), 400

    config = parse_config(CONFIG_PATH)
    rules = build_rules(request.form, config["value_rules"], config["pattern_rules"])

    # 候補リストから確定した値を追加
    for val in request.form.getlist("candidate_val"):
        val = val.strip()
        if val:
            rules.append(MaskRule(pattern=re.compile(re.escape(val)), label="《検出候補》"))

    image_xrefs = [int(x) for x in request.form.getlist("img_xref") if x.isdigit()]

    try:
        regions = json.loads(request.form.get("regions", "[]"))
    except Exception:
        regions = []

    # テキスト候補のbboxもregionsに追加（テキスト検索より確実）
    try:
        candidate_regions = json.loads(request.form.get("candidate_regions", "[]"))
        regions.extend(candidate_regions)
    except Exception:
        pass

    # テキスト候補の文字列: 全ページ走査で同じ文字列を含む行も黒塗りする
    try:
        candidate_texts = [t for t in json.loads(request.form.get("candidate_texts", "[]")) if t.strip()]
    except Exception:
        candidate_texts = []

    # 形式マスク: チェックした候補を形式パターンに汎化して全ページ照合
    generalize = request.form.get("generalize") == "on"

    if not rules and not image_xrefs and not regions and not candidate_texts:
        return jsonify({"error": "有効なマスクルールがありません。値を入力するか自動パターンをONにしてください"}), 400

    suffix = Path(file.filename).suffix.lower()
    tmp_dir = tempfile.mkdtemp()
    tmp_in = Path(tmp_dir) / ("input" + suffix)
    tmp_out = Path(tmp_dir) / ("output" + suffix)
    file.save(str(tmp_in))

    try:
        process_file(tmp_in, tmp_out, rules,
                     image_xrefs if suffix == ".pdf" else None,
                     regions if suffix == ".pdf" else None,
                     candidate_texts if suffix == ".pdf" else None,
                     generalize)
    except Exception as e:
        return jsonify({"error": f"処理エラー: {e}"}), 500

    output_name = Path(file.filename).stem + "_masked" + suffix
    response = send_file(str(tmp_out), as_attachment=True, download_name=output_name)

    # マスク後検査: 対象がまだ残っているページを特定してヘッダーで返す
    if suffix == ".pdf":
        try:
            flagged = audit_pdf(tmp_out, candidate_texts, rules, generalize)
            audit_json = json.dumps(flagged[:50], ensure_ascii=False)
            import base64
            response.headers["X-Mask-Audit"] = base64.b64encode(audit_json.encode()).decode()
        except Exception:
            pass

    return response


if __name__ == "__main__":
    print("マスクツール UI 起動中...")
    print("ブラウザで → http://localhost:5000")
    app.run(debug=False, port=5000)
