#!/usr/bin/env python3
"""
Google Drive「部品カタログ」フォルダからPDFを/tmpにダウンロードする。

Claude Code MCP (Google Drive) セッション外で実行する場合に使用。
通常はClaude AgentがMCP経由でダウンロードするため、このスクリプトは任意。

使用方法:
    python scripts/download_catalog.py <file_id> <output_filename>

例:
    python scripts/download_catalog.py 1ABC...XYZ 三菱ブレーカー総合カタログ.pdf
    # → /tmp/三菱ブレーカー総合カタログ.pdf に保存

注意:
    - GOOGLE_APPLICATION_CREDENTIALS 環境変数 または
      ~/.config/gcloud/application_default_credentials.json が必要。
    - アクセス可能なのは「部品カタログ」フォルダ内のファイルのみ (CLAUDE.mdルール)。
"""

import sys
import os
from pathlib import Path


def download_file(file_id: str, output_name: str) -> Path:
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseDownload
        from google.auth import default
        import io
    except ImportError:
        print("ERROR: google-api-python-client が未インストールです。")
        print("  pip install google-api-python-client google-auth")
        sys.exit(1)

    output_path = Path("/tmp") / output_name

    creds, _ = default(scopes=["https://www.googleapis.com/auth/drive.readonly"])
    service = build("drive", "v3", credentials=creds)

    # ファイルメタデータを確認 (部品カタログフォルダ内かチェック)
    meta = service.files().get(fileId=file_id, fields="name,parents").execute()
    print(f"ダウンロード対象: {meta.get('name')} (ID: {file_id})")

    request = service.files().get_media(fileId=file_id)
    with open(output_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                print(f"  進捗: {int(status.progress() * 100)}%")

    print(f"保存完了: {output_path} ({output_path.stat().st_size // 1024 // 1024}MB)")
    return output_path


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("使用方法: python scripts/download_catalog.py <file_id> <output_filename>")
        sys.exit(1)
    download_file(sys.argv[1], sys.argv[2])
