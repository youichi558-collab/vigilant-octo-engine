# セッション引継ぎメモ

**作成日**: 2026-06-14（2回目更新）  
**次セッション開始時に必ず読むこと**

---

## 最重要: PDFアクセス方式の設計決定

### 問題の結論

`mcp__Google_Drive__read_file_content` はPDFの先頭～約44ページ分しか抽出できない。
選定章（例: ブレーカーカタログ p.145-186）は到達不可。これは根本的な制限であり、小手先の回避策（分割、早見表化など）は失敗と判断した。

### 採用する解決策: Python スクリプトによるカタログ変換（camelot-py）

**方針**: カタログPDFをリポジトリ内の構造化ファイル（JSON/CSV）に変換し、Agent03はローカルファイルを参照する。

**フロー**:
1. `scripts/convert_catalog.py <drive_file_id> <pages> <output_path>` を実装
2. `download_file_content` でPDF取得 → `/tmp/` に保存
3. `camelot-py` でページ指定して表を抽出（AIなし・テキストPDF対応）
4. `database/catalogs/{カタログ名}/` にJSON/CSV保存
5. Agent03はindex.csvでカタログ名を引き、ローカルJSONを参照

**利点**:
- 変換は1回だけ（カタログ改訂時に再実行）
- クエリ時はDrive不要・高速
- AIなしで精度が出る（テキストPDFであることが前提）
- ページ指定可能なため60ページでも600ページでも対応可

### 次セッションの最優先タスク

1. `camelot-py` のインストール確認（`pip install camelot-py[cv]`）
2. `scripts/convert_catalog.py` の実装
3. 三菱ブレーカーカタログ（101-200.pdf、ID: `1T-xj1Nwg8yCbQm3GRiiCRd0Wt90WznXu`）の p.145-186 で動作テスト
4. 成功したら `database/catalogs/三菱ブレーカー/selection_tables.json` に保存
5. Agent03の参照フローをローカルJSONに切り替え

---

## テスト案件 20260614-001 の現状

| 項目 | 内容 |
|------|------|
| 進捗 | spec_summary.md・parts_selection.md ともに作成済み |
| ブレーカー選定 | 選定ルール.md Section 4 の早見表で暫定選定済み（カタログ直読みは未達成） |
| 電磁開閉器 | MSO-T20（3.7kW）/ MSO-T10（1.5kW）— カタログから取得済み |
| 未確認事項 | モータ始動方式・PLCモデル・銘板電流（parts_selection.md Section 5参照） |

カタログ変換スクリプトが完成したら、三菱ブレーカー選定章を読み直してparts_selection.mdのブレーカー選定を検証・更新すること。

---

## 分割済みDriveファイル（三菱ブレーカー総合カタログ）

親フォルダID: `1sPNMd1XclWT4DUFu8eto6HKDKHbE8Q4r`

| ファイル名 | Drive ID | サイズ | 含む原本ページ |
|-----------|---------|--------|--------------|
| 001-100.pdf | `1aBNYAlguz9iFVnAKFbBgtJDsrgqYAPBX` | 14MB | p.1-100 |
| 101-200.pdf | `1T-xj1Nwg8yCbQm3GRiiCRd0Wt90WznXu` | 8.8MB | p.101-200 ← 選定章(p.145-186)がここ |
| 201-300.pdf | `1OMOaso8_nQxz4eR-NhaCQurmswIHjxMR` | 12MB | p.201-300 |
| 301-400.pdf | `1ctH3sC6AR3_cazeNmOG4OPl6nD0ORVmE` | 8MB | p.301-400 |
| 401-500.pdf | `1FbD91jRA2UJ_junzE36jm_Pe-AHdj_wR` | 11.5MB | p.401-500 |
| 501-574.pdf | `1AWDEFrY1Dz7gsAWn_pNf6qZGPM8K35KG` | 12.4MB | p.501-574 |

選定章は `101-200.pdf` の内部 p.45-86（原本p.145-186に対応）。

---

## index.csv 確定状況一覧

### ✅ 確定済み

| メーカー | カテゴリ | カタログファイル | ページ範囲 |
|---------|---------|----------------|-----------|
| 三菱電機 | 電磁開閉器 | 電磁開閉器.pdf | p.27-66 |
| 富士電機 | 電磁接触器 | 電磁接触器、開閉器.pdf | p.19-43 |
| 三菱電機 | ブレーカー | 三菱ブレーカー総合カタログ | p.145-186 |
| 富士電機 | ブレーカー | 富士ブレーカーカタログ.pdf | p.177-216 |
| 三菱電機 | サーボ | ACサーボ.pdf | p.6-42 |
| 富士電機 | サーボ | ALPHA7 カタログ.pdf | p.20-55 |
| キーエンス | PLC | KV-X COM 総合カタログ.pdf | p.6-10 |
| キーエンス | HMI | タッチパネルディスプレイVT5シリーズ.pdf | p.4-5 |

### 🔶 ページ範囲 TBD

| メーカー | カテゴリ | カタログファイル |
|---------|---------|----------------|
| 三菱電機 | インバータ | 総合カタログ.pdf |
| 三菱電機 | サーボ MR-J5 | 総合カタログ.pdf |
| 三菱電機 | PLC | 総合カタログ.pdf |

### ❌ カタログ未入手（低優先度）

| メーカー | カテゴリ |
|---------|---------|
| 富士電機 | インバータ FRENIC-MEGA/Ace |
| 三菱電機 | 端子台 TBシリーズ |
| 富士電機 | 端子台 UKシリーズ |

---

## 注意事項

- Google Drive アクセスは `マイドライブ/部品カタログ/` 以下のみ（読み取り専用）
- Drive全体検索禁止
- CLAUDE.md のGit運用ルール（main直接プッシュ）は、セッション指示（`claude/magical-edison-6lxj94` ブランチ）が優先
