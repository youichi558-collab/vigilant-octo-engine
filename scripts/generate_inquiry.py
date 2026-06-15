"""
質疑書をExcel形式で生成するスクリプト。

使い方:
    python scripts/generate_inquiry.py <project_id> [output_dir]

例:
    python scripts/generate_inquiry.py 20260614-001
    python scripts/generate_inquiry.py 20260614-001 /tmp
"""

import sys
import os
from datetime import date
from openpyxl import Workbook
from openpyxl.styles import (
    Font, PatternFill, Alignment, Border, Side
)
from openpyxl.utils import get_column_letter

# --- 質疑事項定義 ---
SECTIONS = [
    ("設備・装置について", [
        ("Q1",  "設備の用途・動作概要を教えてください。\n（例: 搬送コンベア、加工機、組立装置等）", ""),
        ("Q2",  "駆動するモーターの種類を教えてください。\n（誘導モーター / サーボモーター / ステッピングモーター / その他）", ""),
    ]),
    ("電気・電源について", [
        ("Q3",  "電源の仕様を教えてください。\n（電圧・相数・周波数）", "例: AC200V 3相 50Hz"),
        ("Q4",  "制御回路の電源電圧に指定はありますか？\n（AC200V / AC100V / DC24V / 指定なし）", ""),
        ("Q5",  "引込変圧器の容量（kVA）または短絡容量（kA）を教えてください。", "ブレーカーの遮断容量選定に必要です"),
        ("Q6",  "漏電遮断器（ELB）の設置は必要ですか？\n必要な場合、設置範囲を教えてください。\n（主幹のみ / 分岐ごと / 特定回路）", ""),
    ]),
    ("設置環境について", [
        ("Q7",  "制御盤の設置場所の環境を教えてください。\n（屋内/屋外・粉塵の有無・油の有無・結露の有無等）", "IP等級の選定に使用します"),
        ("Q8",  "設置スペースの制約（高さ・幅・奥行の上限）はありますか？", "制約なければ社内で設計します"),
        ("Q9",  "ケーブルの引き込み方向に指定はありますか？\n（上面 / 下面 / 側面 / 指定なし）", ""),
    ]),
    ("安全・法規について", [
        ("Q10", "非常停止ボタンは必要ですか？", ""),
        ("Q11", "作業者が機械の危険エリアに手を入れる等の作業はありますか？", "安全回路の要否判断に使用します"),
        ("Q12", "海外への輸出・CE対応は必要ですか？", ""),
        ("Q13", "安全カテゴリ・PL（パフォーマンスレベル）の指定はありますか？\n（例: Cat.3 PL d）", "指定がある場合はその値を教えてください"),
        ("Q14", "防爆仕様は必要ですか？", ""),
    ]),
    ("盤仕様・製作について", [
        ("Q15", "制御盤の製作・組立は弊社にご依頼されますか？\n（製作あり / 部品選定のみ / 既設盤改造）", ""),
        ("Q16", "塗装色の指定はありますか？\n（指定なし / 指定あり→マンセル値・RAL番号等を教えてください）", ""),
        ("Q17", "操作方式を教えてください。\n（盤面操作 / 外部信号 / 両方）", ""),
        ("Q18", "操作部品・表示部品（押しボタン・パイロットランプ等）の色・形状に指定はありますか？", ""),
        ("Q19", "内部照明は必要ですか？", ""),
        ("Q20", "ドア錠の種別に指定はありますか？\n（標準取手 / 鍵付き）", ""),
    ]),
    ("配線・部品について", [
        ("Q21", "部品メーカーの指定はありますか？\n（指定あり→メーカー名 / 既設に合わせる→既設メーカー名 / 指定なし）", ""),
        ("Q22", "電線色・配線仕様に指定はありますか？", "指定なければ社内標準を適用します"),
        ("Q23", "電線種別に指定はありますか？", ""),
        ("Q24", "アース母線の設置は必要ですか？", ""),
        ("Q25", "部品の規格認証に指定はありますか？\n（UL認証 / CE対応品 / 指定なし）", ""),
    ]),
    ("図書・検査について", [
        ("Q26", "モーターの銘板に記載されている全負荷電流（A）を教えてください。", "部品選定の精度向上のため"),
        ("Q27", "制御盤からモーターまでの電線の経路長（概算）を教えてください。", "電圧降下計算に使用します"),
        ("Q28", "回路図・配線図の提出は必要ですか？\n必要な場合、提出形式を教えてください。\n（紙 / PDF / DXF）", ""),
        ("Q29", "銘板の言語に指定はありますか？\n（日本語 / 英語 / 両言語）", ""),
    ]),
    ("その他", [
        ("Q30", "既設設備・既設盤の図面・仕様書はありますか？\n（ある場合はご提供をお願いします）", ""),
        ("Q31", "客先仕様書・納入仕様書はありますか？\n（ある場合はご提供をお願いします）", ""),
        ("Q32", "その他、ご要望・ご指定事項があればご記載ください。", ""),
    ]),
]

# --- スタイル定義 ---
COLOR_HEADER_BG   = "1F4E79"  # 濃紺
COLOR_SECTION_BG  = "BDD7EE"  # 薄青
COLOR_NOTE_BG     = "FFF2CC"  # 薄黄
COLOR_ANSWER_BG   = "FFFFFF"  # 白
COLOR_WHITE       = "FFFFFF"
COLOR_BLACK       = "000000"

def thin_border():
    s = Side(style="thin", color=COLOR_BLACK)
    return Border(left=s, right=s, top=s, bottom=s)

def make_header(ws, project_id, today):
    """タイトル・ヘッダー部を作成する"""
    ws.merge_cells("A1:E1")
    c = ws["A1"]
    c.value = f"質 疑 書　－　{project_id}"
    c.font = Font(name="メイリオ", size=16, bold=True, color=COLOR_WHITE)
    c.fill = PatternFill("solid", fgColor=COLOR_HEADER_BG)
    c.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 36

    # (label, value, manual_input)
    # manual_input=True → 人間が手入力する欄（水色背景・空欄）
    meta = [
        ("宛先",     "（客先名） 御中",          False),
        ("設備名称", "",                          True),
        ("件名",     "",                          True),
        ("送付日",   today,                       False),
        ("回答期限", "",                          False),
        ("送付者",   "",                          False),
        ("連絡先",   "",                          False),
    ]
    for i, (label, val, manual) in enumerate(meta, start=2):
        ws[f"A{i}"].value = label
        ws[f"A{i}"].font = Font(name="メイリオ", size=10, bold=True)
        ws[f"A{i}"].fill = PatternFill("solid", fgColor=COLOR_SECTION_BG)
        ws[f"A{i}"].alignment = Alignment(horizontal="center", vertical="center")
        ws[f"A{i}"].border = thin_border()

        ws.merge_cells(f"B{i}:E{i}")
        ws[f"B{i}"].value = val
        ws[f"B{i}"].font = Font(name="メイリオ", size=10)
        ws[f"B{i}"].alignment = Alignment(horizontal="left", vertical="center")
        ws[f"B{i}"].border = thin_border()
        if manual:
            ws[f"B{i}"].fill = PatternFill("solid", fgColor="F2F9FF")

    # 前文
    row = len(meta) + 2
    ws.merge_cells(f"A{row}:E{row}")
    ws[f"A{row}"].value = (
        "下記の事項についてご確認をお願いいたします。"
        "ご多忙のところ恐れ入りますが、回答期限までにご回答いただけますと幸いです。"
    )
    ws[f"A{row}"].font = Font(name="メイリオ", size=10)
    ws[f"A{row}"].alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[row].height = 30
    return row + 1

def make_table_header(ws, row):
    headers = ["No", "確認事項", "回答欄", "備考"]
    widths_col = [1, 2, 3, 4]  # A=No, B=確認事項, C=回答欄, D=備考 → E未使用
    labels = ["No", "確認事項", "回　答　欄", "備考"]
    cols = ["A", "B", "C", "D"]
    for col, label in zip(cols, labels):
        c = ws[f"{col}{row}"]
        c.value = label
        c.font = Font(name="メイリオ", size=10, bold=True, color=COLOR_WHITE)
        c.fill = PatternFill("solid", fgColor=COLOR_HEADER_BG)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = thin_border()
    ws.row_dimensions[row].height = 20
    return row + 1

def make_section(ws, row, section_title):
    ws.merge_cells(f"A{row}:D{row}")
    c = ws[f"A{row}"]
    c.value = f"■ {section_title}"
    c.font = Font(name="メイリオ", size=10, bold=True, color="1F4E79")
    c.fill = PatternFill("solid", fgColor=COLOR_SECTION_BG)
    c.alignment = Alignment(horizontal="left", vertical="center")
    c.border = thin_border()
    ws.row_dimensions[row].height = 20
    return row + 1

def make_question(ws, row, no, question, note):
    # No列
    c = ws[f"A{row}"]
    c.value = no
    c.font = Font(name="メイリオ", size=10, bold=True)
    c.alignment = Alignment(horizontal="center", vertical="top", wrap_text=True)
    c.border = thin_border()

    # 確認事項列
    c = ws[f"B{row}"]
    c.value = question
    c.font = Font(name="メイリオ", size=10)
    c.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
    c.border = thin_border()

    # 回答欄
    c = ws[f"C{row}"]
    c.value = ""
    c.fill = PatternFill("solid", fgColor="F2F9FF")
    c.border = thin_border()
    c.alignment = Alignment(vertical="top", wrap_text=True)

    # 備考
    c = ws[f"D{row}"]
    c.value = note
    c.font = Font(name="メイリオ", size=9, color="595959")
    c.fill = PatternFill("solid", fgColor=COLOR_NOTE_BG) if note else PatternFill("solid", fgColor=COLOR_ANSWER_BG)
    c.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
    c.border = thin_border()

    # 行高さ: 改行数と文字数から推定
    newlines = question.count("\n") + 1
    # B列の列幅50文字換算で折り返し行数を推定
    max_line_len = max(len(l) for l in question.split("\n"))
    wrap_lines = max(1, -(-max_line_len // 46))  # 切り上げ除算
    total_lines = max(newlines, wrap_lines, 2)
    ws.row_dimensions[row].height = max(total_lines * 24, 60)
    return row + 1

def generate(project_id, output_dir="."):
    wb = Workbook()
    ws = wb.active
    ws.title = "質疑書"

    # 列幅設定（全列等幅）
    ws.column_dimensions["A"].width = 8    # No
    ws.column_dimensions["B"].width = 50   # 確認事項
    ws.column_dimensions["C"].width = 50   # 回答欄
    ws.column_dimensions["D"].width = 50   # 備考

    today = date.today().strftime("%Y-%m-%d")
    row = make_header(ws, project_id, today)
    row = make_table_header(ws, row)

    for section_title, questions in SECTIONS:
        row = make_section(ws, row, section_title)
        for no, question, note in questions:
            row = make_question(ws, row, no, question, note)

    # 印刷設定
    ws.page_setup.orientation = "portrait"
    ws.page_setup.paperSize = 9  # A4
    ws.page_margins.left = 0.5
    ws.page_margins.right = 0.5
    ws.page_margins.top = 0.75
    ws.page_margins.bottom = 0.75
    ws.print_title_rows = "1:1"

    out_path = os.path.join(output_dir, f"inquiry_{project_id}.xlsx")
    wb.save(out_path)
    print(f"生成完了: {out_path}")
    return out_path

if __name__ == "__main__":
    pid = sys.argv[1] if len(sys.argv) > 1 else "template"
    out = sys.argv[2] if len(sys.argv) > 2 else "."
    generate(pid, out)
