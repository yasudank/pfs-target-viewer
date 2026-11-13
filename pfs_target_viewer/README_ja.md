[English](README.md) | **日本語**

---

# PFS Target & Spectrum Viewer (Web Application)

Subaru Prime Focus Spectrograph (PFS) のコアッド観測メタデータ（`pfs_metadata.sqlite3`）および生スペクトルデータ（`extracted_targets/` の FITS / PNG）を可視化・検索・分析するためのスタンドアロン Web アプリケーションです。

---

## 主な特徴

- 🚀 **PFS パイプライン非依存 (Pipeline-Free) & 大規模データセット完全対応**
  - `lsst-scipipe` や `pfs_pipe2d` 等の重厚な専用環境を一切必要とせず、標準的な Python 3.10+ 環境（`astropy`, `fastapi`, `uvicorn`, `numpy` のみ）で完全に動作します。
  - 20万件規模の大規模カタログやディレクトリシャーディング（`fits/NNN/`, `png/NNN/`）にネイティブ対応。
  - 任意のマシン（個人のラップトップ、解析ワークステーション、クラウドサーバー等）へフォルダごとコピーして即座に同じ環境を再現できます。
- 🔍 **柔軟な検索・フィルタリング・サーバーサイドクエリキャッシュ**
  - **全件対象の即座ソート**: サーバー内インメモリクエリキャッシュ（`SQL_CACHE`）により、フィルター条件に合致する全天体（数万〜20万件）を対象にした赤方偏移（Redshift）、後退速度（Velocity $v=c \cdot z$）、Target ID、`catId`、分類確率などによるソートをサブミリ秒で実行。
  - `obCode` や 64-bit `objId` によるキーワード検索（部分一致対応）。
  - カタログID (`catId`) によるサンプルの絞り込み（カタログ毎の件数バッジ付き）。
  - 天体分類（`ALL`, `GALAXY`, `QSO`, `STAR`）による絞り込み。
  - 赤方偏移範囲（$z_{min} \le z \le z_{max}$）による絞り込み。
  - 「With Spectra」チェックボックス（FITS / PNG 抽出済み天体のみ表示）。
  - 表示カラムカスタマイズ（Column Customizer）。
  - 10 / 25 / 50 / 100 件切替の高速ページネーション。
- 🌌 **モルワイデ全天球プロット & 視野連動絞り込み (Mollweide Sky Map)**
  - モルワイデ楕円図法（2:1 アスペクト比維持）による全天 RA / Dec 投影表示（天文学の東が左慣例）。
  - **中央子午線（RA）回転コントロール**: スライダー（$0^\circ \sim 360^\circ$）またはプリセットボタン（$0^\circ, 60^\circ, 120^\circ, 180^\circ, 240^\circ, 300^\circ$）で瞬時に視野を回転。
  - **「Filter Table by View」視野連動絞り込み**: 天球マップ上で関心のある天域にズーム・パンし、ボタン 1 つで現在の表示視野（バウンディングボックス）内の天体のみにテーブルを空間絞り込み。
  - **デュアル表示スコープ & フォーカスリング**: `📄 Page`（現在テーブル表示中の天体）と `🌐 All Filtered`（全天体・20万件以上を WebGL `scattergl` で高速描画）を切り替え可能。
  - **データセット連動の超高速全天球座標キャッシュ**: 起動時にデータセット側ディレクトリに `.{dbname}_sky_cache.json.gz` を自動生成し、数ミリ秒でのロードおよび HTTP ETag (304) / GZip 配信を実現。
- 💻 **高度な SQL クエリ実行モード & スキーマエクスプローラー**
  - Standard Filters モードに加え、自由な SQL を記述できる SQL モードを搭載。
  - スキーマエクスプローラー（テーブル一覧、カラム型、レコード件数の確認）と連動した編集エリア。
  - **天文学向け拡張 SQL 関数**:
    - `CONE_SEARCH(ra, dec, center_ra, center_dec, radius_arcsec)`: 高速コーンサーチ
    - `BOX_SEARCH(ra, dec, ra_min, ra_max, dec_min, dec_max)`: 矩形領域検索
    - 数学関数: `SQRT`, `POW`, `COS`, `SIN`, `RADIANS`, `DEGREES`, `LOG10`, `LN`, `EXP`
  - プリセット SQL テンプレート（コーンサーチ、高赤方偏移クエーサー、輝線フラックス順、ソルバー警告等）。
  - `ts.combination` や JOIN 先テーブルの任意カラムを結果テーブルに動的展開。
- 🌌 **光学画像カットアウト連携 (HSC & Pan-STARRS)**
  - 詳細モーダル内で Hyper Suprime-Cam (HSC) SSP の光学 3 色合成カラー画像を自動取得・表示。
  - HSC 未撮影領域やダミー白色フレームを自動判定し、Pan-STARRS1 (PS1) カラーカットアウトへ自動フォールバック。
- 🖼️ **PNG スペクトル画像クイックルック & 連続閲覧 (Sequential Browsing)**
  - サムネイルまたは天球マップから瞬時に高解像度 PNG スペクトル画像モーダルを起動。
  - キーボードの矢印キー（`←` / `→`）または左右のフローティング矢印ボタンで、モーダルを開いたまま次々と前後の天体を連続プレビュー。
  - ページ末尾到達時に自動で次ページを取得し、シームレスな連続閲覧を維持。
  - モーダル内の「Open Interactive Spectrum」から推定赤方偏移を引き継いでインタラクティブビューアへシームレスに遷移可能。
- 📊 **詳細パラメータの深層閲覧 (Deep Inspection)**
  - ソルバーエラー・警告フラグ (`solver_results`)
  - 赤方偏移候補一覧 (`redshift_candidates`: 各モデルの $z$, 誤差, 確率, reduced $\chi^2$, $p$-value 等)
  - 輝線・吸収線測定値 (`line_measurements`: 検出波長, フラックス, 等価幅 EW, $\sigma$ 等)
- 📈 **インタラクティブ FITS スペクトルビューア (Plotly.js)**
  - `pfsObject` FITS ファイルの生データをブラウザ上でインタラクティブに可視化（ズーム、パン、正確な波長・フラックスのホバー表示）。
  - クライアントサイドでの動的逆分散ビン幅調整（Raw, 0.2 nm, 0.5 nm, 1.0 nm, 2.0 nm）。
  - $1\sigma$ ノイズ帯およびバッドピクセルマスクのシェーディング表示。
  - 主要な輝線・吸収線のオーバーレイ（グラフのズーム時も波長位置に固定表示）：
    - **輝線**: Lyα, C IV, C III], Mg II, [O II], Hβ, [O III], Hα, [N II], [S II]
    - **吸収線**: Ca II H/K, G-band, Mg b, Na D
  - **リアルタイム Redshift スライダー**: スライダーをドラッグすると輝線・吸収線の位置がリアルタイムに追従し、目視での赤方偏移の同定・確認が可能。
  - 個別露出観測リスト（Visit, Arm, Spectrograph, 露出時間）の表示。
  - FITS 生ファイルおよび PNG 画像の直接ダウンロード。

---

## ディレクトリ構成

```text
pfs_target_viewer/
├── app.py                 # FastAPI バックエンドサーバー
├── requirements.txt       # 依存ライブラリ一覧
├── run_viewer.sh          # ワンクリック起動スクリプト (venv自動構築)
├── README.md              # ビューア詳細マニュアル (English)
├── README_ja.md           # 本ドキュメント (日本語)
├── templates/
│   └── index.html         # ダッシュボード HTML テンプレート
└── static/
    ├── css/
    │   └── style.css      # ダークテーマ・モダンデザイン CSS
    └── js/
        ├── app.js         # クライアントサイド UI & Plotly 制御
        └── plotly.min.js  # オフライン用 Plotly.js ライブラリ
```

---

## セットアップ手順

### 方法 1: 付属の起動スクリプトを使用（推奨・最も簡単）

付属の `run_viewer.sh` は、仮想環境 `.venv_viewer` の作成からライブラリのインストール、サーバー起動まで全自動で行います。

```bash
cd pfs_target_viewer
./run_viewer.sh
```

ポート番号を変更したい場合：
```bash
PORT=8088 ./run_viewer.sh
```

---

### 方法 2: 標準の `venv` と `pip` を使用して手動セットアップ

任意のマシン（Linux / macOS / Windows WSL）で手動で環境を構築する場合：

1. **仮想環境の作成**:
   ```bash
   cd pfs_target_viewer
   python3 -m venv .venv_viewer
   source .venv_viewer/bin/activate
   ```

2. **依存パッケージのインストール**:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. **サーバーの起動**:
   ```bash
   python app.py --port 8090
   ```

---

### 方法 3: `uv` を使用したセットアップ

```bash
cd pfs_target_viewer
uv venv .venv_viewer
uv pip install -r requirements.txt --python .venv_viewer
.venv_viewer/bin/python app.py --port 8090
```

---

## サーバーへのアクセス方法

### 1. ローカルマシンで動かしている場合
ブラウザで以下のアドレスを開きます：
```
http://localhost:8090
```

### 2. リモートサーバーで動かしている場合
お使いのローカル PC から SSH ポートフォワーディングで接続します：
```bash
ssh -L 8090:localhost:8090 user@<remote-host>
```
接続後、ローカル PC のブラウザで `http://localhost:8090` を開いてください。

---

## コマンドライン引数 / データディレクトリの指定

`pfs_metadata.sqlite3` と `extracted_targets/` が存在するディレクトリを直接指定して起動できます。

```bash
# 方法 1: 位置引数でディレクトリを指定（推奨・最もシンプル）
./run_viewer.sh /path/to/dataset
python app.py /path/to/dataset

# 方法 2: --dir (-d) オプションで指定
./run_viewer.sh --dir /path/to/dataset
python app.py -d /path/to/dataset

# 方法 3: 環境変数で指定
export PFS_DIR=/path/to/dataset
./run_viewer.sh
```

### 引数一覧

```bash
python app.py [-h] [-d OPT_DIR] [-c CONFIG] [--host HOST] [--port PORT] [--db DB] [--data-dir DATA_DIR] [target_dir]
```

- `target_dir` (位置引数): `pfs_metadata.sqlite3` と `extracted_targets/` が存在するディレクトリパス（省略時はデフォルトで `..`）
- `-d, --dir, --dataset-dir`: `pfs_metadata.sqlite3` と `extracted_targets/` が存在するディレクトリパス
- `-c, --config`: 複数データセットの設定ファイル（後述。省略時は `app.py` と同じディレクトリの `datasets.toml` があれば使用）
- `--host`: バインドするホスト名（デフォルト: `0.0.0.0`）
- `--port`: リッスンするポート番号（デフォルト: `8090`）
- `--db`: SQLite データベースファイルへの個別明示パス（個別指定時に `--dir` より優先）
- `--data-dir`: `extracted_targets` ディレクトリへの個別明示パス（個別指定時に `--dir` より優先）
- `--security-log`: 不正アクセス遮断用のセキュリティログのパス（後述。`none` で無効）

---

## 複数データセットの切り替え（設定ファイル）

設定ファイル `datasets.toml` に複数のデータセットを登録しておくと、ブラウザでアクセスしたときにデータセットの選択画面が表示されます。データセットごとにパスワードを設定することもできます。

```bash
cp datasets.example.toml datasets.toml   # app.py と同じディレクトリに置くと自動で読み込まれる
vi datasets.toml
./run_viewer.sh

# 別の場所の設定ファイルを使う場合:
./run_viewer.sh --config /path/to/datasets.toml
```

```toml
[[datasets]]
id = "s26b047-ql"                              # URL (?ds=...) で使う ID。省略時は name から生成
name = "S26B-047 QL"
description = "Quick-look reduction (run31)"
dir = "/mnt/ugnas/work/LSST/PFS/S26B-047/QL"   # pfs_metadata.sqlite3 と extracted_targets/ があるディレクトリ
password = "secret"                            # 省略すると誰でも閲覧可能

[[datasets]]
name = "S26A-104"
db = "/path/to/pfs_metadata.sqlite3"           # dir の代わりに個別指定も可能
data_dir = "/path/to/extracted_targets"
```

- 選択画面は `/datasets` です。閲覧中もヘッダーの **⇄ Switch** ボタンで戻り、別のデータセットを開けます。
- データセットの選択とパスワード入力の状態はブラウザごとに保持されます（既定で 7 日間、`session_days` で変更可）。複数の人が同時に別々のデータセットを閲覧できます。同じブラウザの別タブで別のデータセットを開いても干渉しません。
- `datasets.toml` は変更すると自動で再読み込みされるため、データセットの追加・削除・パスワード変更にサーバーの再起動は不要です。パスワードを変更すると、そのデータセットのログイン状態は無効になります。
- パスワードは平文で書くため、`datasets.toml` は `.gitignore` で git の管理対象外にしています。ファイルのパーミッションにも注意してください。
- `secret_key` を設定しない場合はサーバー起動のたびにランダムな鍵が作られるため、再起動後はパスワードの再入力が必要です。
- `--dir` などでディレクトリも指定した場合は、そのデータセットが設定ファイルのデータセットに加えて一覧の先頭に表示されます。データセットが 1 つだけでパスワードもない場合は、従来どおり選択画面を経由せずに表示されます。

---

## 不正アクセスの遮断（fail2ban）

外部に公開しているマシンでは、脆弱性スキャナーなどからのアクセスを fail2ban でファイアウォールごと遮断できます。

ビューアは不審なリクエストを、接続元 IP 付きでセキュリティログに 1 行ずつ記録します。ログの場所は既定で `~/.local/state/pfs-target-viewer/security.log` で、`--security-log PATH` で変更、`--security-log none` で無効にできます。fail2ban は root で動き、NFS 上のファイルを読めないことが多いため、ローカルディスクに置いてください。

| event | 内容 | 既定で遮断の対象 |
|---|---|---|
| `not_found` | ビューアに存在しない URL（`/wp-login.php`、`/.env` など） | ✅ |
| `bad_password` | データセットのパスワード間違い | ✅ |
| `method_not_allowed` | 不正な HTTP メソッド | ✅ |
| `unauthorized` | データセット未選択での API アクセス（セッション切れの正規ユーザーでも起きる） | ❌（記録のみ） |

実在する天体のスペクトルや FITS がないための 404 や、ブラウザが自動で取りに来る `/favicon.ico` などは記録しません。

### 導入手順（root 権限が必要）

```bash
sudo apt install fail2ban
sudo cp fail2ban/filter.d/pfs-viewer.conf /etc/fail2ban/filter.d/
sudo cp fail2ban/jail.d/pfs-viewer.local  /etc/fail2ban/jail.d/
sudo vi /etc/fail2ban/jail.d/pfs-viewer.local   # logpath・port・ignoreip を環境に合わせて確認
sudo systemctl enable --now fail2ban

# 判定ルールがログに一致するかの確認
sudo fail2ban-regex ~/.local/state/pfs-target-viewer/security.log /etc/fail2ban/filter.d/pfs-viewer.conf
```

既定では、10 分間に 5 回不審なリクエストを送った IP を 1 時間遮断します。繰り返す IP は遮断時間が延び、最長 1 週間です。`127.0.0.1` と `192.168.0.0/16`（LAN）は遮断しません。

```bash
sudo fail2ban-client status pfs-viewer               # 遮断中の IP 一覧
sudo fail2ban-client set pfs-viewer unbanip 1.2.3.4  # 遮断の解除
```
