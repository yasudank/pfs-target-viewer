[English](README.md) | **日本語**

---

# PFS Target & Spectrum Viewer

Subaru Prime Focus Spectrograph (PFS) のコアッド観測メタデータ集約データベースの構築、天体スペクトル生データ（FITS）およびプロット（PNG）の抽出、ならびにインタラクティブな Web スペクトルビューアを提供する統合ツールキットです。

---

## 📁 ディレクトリ構成

```text
pfs-target-viewer/
├── .gitignore
├── README.md                      # プロジェクト全体ガイド (English)
├── README_ja.md                   # 本ドキュメント (日本語)
├── download_data.sh               # Hugging Face データセット自動取得スクリプト (Bash)
├── download_data.py               # Hugging Face データセット自動取得スクリプト (Python)
├── build_pfs_database.py          # [Step 1] pfsConfig & pfsCoZCandidates から SQLite DB を構築
├── export_pfs_targets.py          # [Step 2] ターゲットごとの pfsObject FITS および PNG プロットを抽出
├── run_pfs.py                     # PFS パイプラインカーネル実行ラッパー
└── pfs_target_viewer/             # [Step 3] スタンドアロン Web アプリケーション
    ├── README.md                  # ビューア詳細マニュアル (English)
    ├── README_ja.md               # ビューア詳細マニュアル (日本語)
    ├── app.py                     # FastAPI バックエンドサーバー & FITS/SQLite パーサー
    ├── requirements.txt           # ビューア用依存パッケージ一覧 (PFS パイプライン非依存)
    ├── run_viewer.sh              # ビューア起動スクリプト (venv 自動作成)
    ├── templates/
    │   └── index.html             # ダッシュボード UI テンプレート
    └── static/
        ├── css/
        │   └── style.css          # 天文解析向けダークテーマ CSS
        └── js/
            ├── app.js             # UI 状態管理・動的ビン化・Plotly 制御
            └── plotly.min.js      # オフライン完全対応 Plotly.js ライブラリ
```

---

## 🚀 ワークフロー

本ツールキットは、以下のステップでデータを生成・可視化します。

```
[PFS Butler Repository]
       │
       ▼  (run_pfs.py build_pfs_database.py)
[pfs_metadata.sqlite3]  ─── 13,000+ 天体のパラメータ集約
       │
       ▼  (run_pfs.py export_pfs_targets.py)
[extracted_targets/]    ─── fits/ (pfsObject生データ) & png/ (スペクトル図)
       │
       ▼  (cd pfs_target_viewer && ./run_viewer.sh)
[Web Dashboard (http://localhost:8090)] ─── 検索・詳細検査・Plotly インタラクティブ解析
```

---

### Step 1: メタデータデータベースの構築 (`build_pfs_database.py`)

PFS Gen3 Butler リポジトリから `pfsConfig` および `pfsCoZCandidates` を読み込み、天体サマリーやソルバー結果、輝線測定値をリレーショナルデータベース SQLite (`pfs_metadata.sqlite3`) に集約します。

```bash
# PFS パイプライン環境で実行
python run_pfs.py build_pfs_database.py
```

- **生成物**: `pfs_metadata.sqlite3`
- **主な格納テーブル**:
  - `v_target_summary`: 天体ごとの代表パラメータ（Redshift, 分類確率, 座標, obCode 等）
  - `solver_results`: 各ソルバーの実行結果・警告フラグ
  - `redshift_candidates`: 候補モデル一覧
  - `line_measurements`: 輝線・吸収線の測定値

---

### Step 2: ターゲット生データ (FITS) & PNG の抽出 (`export_pfs_targets.py`)

データベースに登録された全天体について、生スペクトル (`pfsObject` FITS) を生データとして保存し、赤方偏移に対応した輝線・吸収線位置をオーバーレイしたスペクトルプロット (PNG) を一括抽出します。

```bash
# PFS パイプライン環境で実行
python run_pfs.py export_pfs_targets.py
```

- **生成物**: `extracted_targets/`
  - `fits/pfsObject_{obCode}_{catId}_{objId}.fits` (全天体の生スペクトル)
  - `png/spec_{obCode}_{catId}_{objId}.png` (全天体のクイックルックプロット)

---

### 📥 共同研究者向け: 事前生成済みデータセットの取得 (`download_data.sh`)

PFS パイプライン環境を持たない共同研究者や別のマシンでビューアを利用する場合、Step 1 および Step 2 を実行する必要はありません。Hugging Face に配置された事前生成済みデータセット（`pfs_metadata.sqlite3` および `extracted_targets.tar.gz`）を一括ダウンロード・展開できます。

> **完全な仮想環境分離**: `download_data.sh` / `download_data.py` は、ホストのシステム Python 環境に**一切影響を与えません**。プロジェクト専用の仮想環境（`pfs_target_viewer/.venv_viewer`）を自動作成し、その中に `huggingface_hub` およびビューアの全依存ライブラリをインストールして実行します。データ取得が完了した時点で Web ビューアの環境構築も完了しているため、即座に `./run_viewer.sh` を起動できます。

> [!IMPORTANT]
> **ダウンロード容量と必要空きディスク容量について**:
> - **ダウンロード転送量**: 約 **8.0 GB**（データベース 157 MB ＋ 圧縮アーカイブ `extracted_targets.tar.gz` 7.8 GB）
> - **展開後のデータサイズ**: 約 **11.2 GB**（`fits/`: 7.6 GB、`png/`: 3.5 GB、データベース: 157 MB）
> - **推奨される空きディスク容量**: **20 GB 以上**  
>   *（セットアップ時には、圧縮アーカイブ（7.8 GB）と展開後の生データ（11.2 GB）が一時的に両方ディスク上に存在するため、最低 20 GB 程度の空き容量が必要です。展開完了後は `extracted_targets.tar.gz` を削除して 7.8 GB の空き容量を解放できます。）*
> - **ネットワーク環境**: 高速かつ安定したブロードバンド環境（有線LANやWi-Fi等）での実行を推奨します。

```bash
# Hugging Face Access Token (Read) を設定して実行
export HF_TOKEN="hf_xxxxxxxxxxxx"
./download_data.sh

# または Python で実行する場合:
python download_data.py
```

---

### Step 3: Web ビューアの起動 (`pfs_target_viewer/`)

**PFS パイプライン（`pfs_pipe2d`, `lsst-scipipe`）に一切依存せず**、軽量な Python 標準環境（FastAPI, Astropy, NumPy）のみで動作します。任意のマシン（個人のラップトップ、解析ワークステーション等）へフォルダごとコピーして即座に同じ環境を再現可能です。

```bash
cd pfs_target_viewer
./run_viewer.sh
```

ブラウザで `http://localhost:8090` にアクセスします。

#### 主な機能:
1. **柔軟な検索・フィルタリング・ページネーション**:
   - `obCode` や 64-bit `objId` によるキーワード検索
   - 天体分類（`GALAXY`, `QSO`, `STAR`）によるワンクリック絞り込み
   - 赤方偏移範囲（$z_{min} \le z \le z_{max}$）による絞り込み
   - 13,000 件以上の天体を高速ページネーションでスムーズに閲覧
2. **詳細パラメータの深層閲覧 (`📋 Details`)**:
   - モデル候補一覧 (`redshift_candidates`: 各モデルの $z$, 誤差, 確率, reduced $\chi^2$, $p$-value 等)
   - 輝線・吸収線測定値 (`line_measurements`: 検出波長, フラックス, 等価幅 EW, $\sigma$ 等)
   - ソルバーエラー・警告フラグ (`solver_results`)
3. **インタラクティブ FITS スペクトルビューア (`📈 Plot`)**:
   - `pfsObject` FITS ファイルから波長・フラックス配列を直接読み込み、Plotly.js でズーム・パン描画
   - クライアントサイドでの動的ビン幅調整（Raw, 0.2 nm, 0.5 nm, 1.0 nm, 2.0 nm）
   - $1\sigma$ ノイズ帯およびバッドピクセルマスクのシェーディング表示
   - 主要輝線・吸収線のオーバーレイ
   - **リアルタイム Redshift スライダー**: スライダーを動かすと輝線位置がリアルタイムに追従
   - 個別露出観測リスト（Visit, Arm, Spectrograph, 露出時間）の表示
   - FITS 生ファイルおよび PNG 画像の直接ダウンロード

---

## 🛠️ 環境要件

- **Step 1 & 2 (データ抽出)**:
  - PFS 2D パイプライン環境 (`pfs_pipe2d`, `lsst-scipipe`)
- **Step 3 (Web ビューア)**:
  - Python 3.10+
  - 依存ライブラリ: `fastapi`, `uvicorn`, `astropy`, `numpy`, `jinja2`
  - ※ 付属の `run_viewer.sh` を実行すると専用仮想環境 `.venv_viewer` が自動構築されます。

---

## 📄 ライセンス

本プロジェクトは研究・学術目的で開発されています。
