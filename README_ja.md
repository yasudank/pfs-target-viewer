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

**PFS パイプライン（`pfs_pipe2d`, `lsst-scipipe`）に一切依存せず**、軽量な Python 標準環境（FastAPI, Astropy, NumPy）のみで動作します。任意のマシン（個人のラップトップ、解析ワークステーション等）へフォルダごとコピーして即座に同じ環境を再現可能です。20万件規模の大規模カタログでも軽快に動作するよう設計されています。

```bash
cd pfs_target_viewer
./run_viewer.sh

# 別のディレクトリに pfs_metadata.sqlite3 と extracted_targets/ がある場合:
./run_viewer.sh /path/to/dataset
```

ブラウザで `http://localhost:8090` にアクセスします。

---

## ✨ 主な機能と特徴

### 1. 柔軟な検索・フィルタリング・サーバーサイドクエリキャッシュ
- **全件対象の即座ソート & ページネーション**:
  - サーバーサイドのインメモリクエリキャッシュ（`SQL_CACHE`）により、フィルター条件に合致する全天体（数万〜20万件）を対象にした赤方偏移（Redshift）、後退速度（Velocity $v=c \cdot z$）、Target ID、`catId`、分類確率などによるソートをサブミリ秒で実行。
  - 1ページ分だけでなく、**検索結果全件に対する正確なソート順**を保ったままページ移動（10 / 25 / 50 / 100 件切替）が可能です。
- **多彩な検索・絞り込みツールバー**:
  - `obCode`（部分一致）や 64-bit `objId`（完全一致）によるリアルタイム検索。
  - カタログID (`catId`) ドロップダウン（カタログ毎の件数バッジ付き）。
  - 分類ピルボタン（`ALL`, `GALAXY`, `QSO`, `STAR`）によるワンクリック絞り込み。
  - 赤方偏移範囲（$z_{min} \le z \le z_{max}$）指定。
  - 「With Spectra」チェックボックス（FITS / PNG が抽出済みの天体のみを素早く抽出）。
  - テーブル表示カラムのカスタマイズ（Column Customizer）。

### 2. モルワイデ全天球プロット & 視野連動絞り込み (Mollweide All-Sky Map)
- **モルワイデ図法（2:1 アスペクト比）による全天表示**:
  - 赤経（RA）と赤緯（Dec）を天文学の慣例（東が左）に従ってモルワイデ楕円天球上に投影。
  - ズームやパンを行っても幾何学的アスペクト比（2:1）を維持。
- **中央子午線（RA）回転コントロール**:
  - スライダー（$0^\circ \sim 360^\circ$）またはプリセットボタン（$0^\circ, 60^\circ, 120^\circ, 180^\circ, 240^\circ, 300^\circ$）により、観測領域を中心に据えた最適な天球ビューへ瞬時に回転可能。
- **デュアル表示スコープ & フォーカスリング**:
  - `📄 Page`（現在テーブルに表示中の天体）と `🌐 All Filtered`（全天体・20万件以上を WebGL `scattergl` で高速描画）を切り替え可能。現在ページの天体は白色のフォーカスリングでハイライト重畳されます。
- **「Filter Table by View」視野連動絞り込み**:
  - 天球マップ上で関心のある領域をズーム・パンし、「Filter Table by View」をクリックすると、現在の表示視野（バウンディングボックス）内に含まれる天体のみで一覧テーブルを空間的に絞り込みます（視野枠のオーバーレイ表示付き）。
- **データセット連動の超高速全天球座標キャッシュ**:
  - 起動時またはデータセット切替時に全天座標データを自動生成し、データセット側のディレクトリに圧縮キャッシュ（`.{dbname}_sky_cache.json.gz`）として保存。
  - 2回目以降の起動や全天球表示はディスクおよびサーバーメモリキャッシュから数ミリ秒で即座にロードされ、HTTP ETag (304 Not Modified) / GZip 圧縮によりネットワーク転送もゼロ遅延で完了します。

### 3. 高度な SQL クエリ実行モード & スキーマエクスプローラー
- **Web 上で自在に発行できる SQL Query Editor**:
  - Standard Filters モードに加え、自由な SQL を記述できる SQL モードを搭載。
  - スキーマエクスプローラー（テーブル一覧、カラム型、レコード件数の確認）と高さを揃えた編集エリア。
- **天文学向け拡張 SQL 関数**:
  - `CONE_SEARCH(ra, dec, center_ra, center_dec, radius_arcsec)`: 指定座標・半径（秒角）でのコーンサーチ
  - `BOX_SEARCH(ra, dec, ra_min, ra_max, dec_min, dec_max)`: 矩形領域検索
  - 数学関数: `SQRT`, `POW`, `COS`, `SIN`, `RADIANS`, `DEGREES`, `LOG10`, `LN`, `EXP` などを SQLite 内で直接実行可能。
- **プリセット SQL テンプレート**:
  - コーンサーチ、高赤方偏移クエーサー抽出、輝線フラックス順ソート、ソルバー警告フラグ抽出などの実践的な SQL テンプレートをワンクリック挿入可能。
- **動的カラムマッピング**:
  - `ts.combination` や `lm.lineFlux` など、任意のテーブル結合（JOIN）によって SELECT された非標準カラムも、結果テーブルに自動的に個別列として展開・表示されます。

### 4. 光学画像カットアウト連携 (HSC & Pan-STARRS)
- **多波長イメージングとの即座比較**:
  - 天体の詳細モーダル内で、Hyper Suprime-Cam (HSC) SSP の光学 3 色合成カラー画像を自動取得して表示。
  - **インテリジェント・フォールバック**: HSC の観測領域外やダミー白色フレーム（白飛びデータ）を自動判定し、自動的に Pan-STARRS1 (PS1) のカラーカットアウトへとフォールバックして表示します。

### 5. PNG スペクトル画像クイックルック & 連続閲覧 (Sequential Browsing)
- **スライドショー感覚のスムーズな天体精査**:
  - テーブルのサムネイルまたは天球プロットのマーカーをクリックすると、高解像度 PNG スペクトル画像がモーダルでポップアップ。
  - キーボードの矢印キー（`←` / `→`）または左右のフローティング矢印ボタンで、モーダルを開いたまま次々と前後の天体を連続プレビュー。
  - ページ末尾に到達した場合はバックグラウンドで自動的に次ページを取得し、シームレスな連続閲覧を維持。
  - モーダルからワンクリックで推定赤方偏移を引き継いだまま Plotly インタラクティブビューアへ遷移可能。

### 6. 詳細パラメータの深層閲覧 (`📋 Details`)
- **網羅的な解析結果の検証**:
  - モデル候補一覧 (`redshift_candidates`: 各モデルの $z$, 誤差, 確率, reduced $\chi^2$, $p$-value 等)
  - 輝線・吸収線測定値 (`line_measurements`: 検出波長, フラックス, 等価幅 EW, $\sigma$ 等)
  - ソルバーエラー・警告フラグ (`solver_results`)

### 7. インタラクティブ FITS スペクトルビューア (`📈 Plot`)
- **Plotly.js による高機能スペクトル解析**:
  - `pfsObject` FITS ファイルの生データをブラウザ上でインタラクティブに可視化（ズーム、パン、正確な波長・フラックスのホバー表示）。
  - クライアントサイドでの動的逆分散ビン幅調整（Raw, 0.2 nm, 0.5 nm, 1.0 nm, 2.0 nm）。
  - $1\sigma$ ノイズ帯およびバッドピクセルマスクのシェーディング表示。
  - 主要な輝線・吸収線のオーバーレイ（グラフのズーム時も波長位置に固定表示）：
    - **輝線**: Lyα, C IV, C III], Mg II, [O II], Hβ, [O III], Hα, [N II], [S II]
    - **吸収線**: Ca II H/K, G-band, Mg b, Na D
  - **リアルタイム Redshift スライダー**: スライダーをドラッグすると輝線・吸収線の位置がリアルタイムに追従し、目視での赤方偏移の同定・確認が可能。
  - 個別露出観測リスト（Visit, Arm, Spectrograph, 露出時間）の表示。
  - FITS 生ファイルおよび PNG 画像の直接ダウンロード。

### 8. 大規模データセット向けアーキテクチャ (Phase 2 Sharding)
- **20万件規模への完全対応**:
  - ファイルシステム上の 1 ディレクトリあたりのエントリ数上限やパフォーマンス低下を回避するため、FITS / PNG をサブディレクトリ（`fits/000/`, `png/000/` 等）へ分散配置するシャーディング形式に対応。
  - データベース内にファイルパスインデックスを持つ構成、従来のフラット配置、シャーディング配置のいずれも自動認識してシームレスに読み込みます。

---

## 🛠️ 環境要件

- **Step 1 & 2 (データ抽出)**:
  - PFS 2D パイプライン環境 (`pfs_pipe2d`, `lsst-scipipe`)
- **Step 3 (Web ビューア)**:
  - Python 3.10+
  - 依存ライブラリ: `fastapi`, `uvicorn`, `astropy`, `numpy`, `jinja2`, `python-multipart`
  - ※ 付属の `run_viewer.sh` を実行すると専用仮想環境 `.venv_viewer` が自動構築されます。

---

## 📄 ライセンス

本プロジェクトは研究・学術目的で開発されています。
