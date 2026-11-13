# PFS Target & Spectrum Viewer

Subaru Prime Focus Spectrograph (PFS) のコアッド観測メタデータ（`pfs_metadata.sqlite3`）および生スペクトルデータ（`extracted_targets/` の FITS / PNG）を可視化・検索・分析するためのスタンドアロン Web アプリケーションです。

---

## Key Features & Highlights

- 🚀 **Pipeline-Free & Large Dataset Scalability**
  - Runs completely independently of heavy pipeline environments (`lsst-scipipe`, `pfs_pipe2d`) on standard Python 3.10+ (`fastapi`, `uvicorn`, `astropy`, `numpy`).
  - Native support for large-scale datasets (200,000+ targets) and directory sharding (`fits/NNN/`, `png/NNN/`).
  - Seamlessly portable across laptops, workstations, and servers.
- 🔍 **Search, Filter & Server-Side Query Caching**
  - **Full-Dataset Instant Sorting**: Server-side in-memory query caching (`SQL_CACHE`) allows instant sorting by Redshift, Velocity ($v = c \cdot z$), Target ID, `catId`, or classification probabilities across all matching records (200,000+ targets) in sub-milliseconds.
  - Real-time search by `obCode` (substring) or 64-bit `objId` (exact match).
  - Catalog ID (`catId`) dropdown with live target count badges.
  - Classification filter pills (`ALL`, `GALAXY`, `QSO`, `STAR`).
  - Redshift range filtering ($z_{min} \le z \le z_{max}$, e.g. $z \ge 6.0$).
  - "With Spectra" checkbox to quickly filter targets with extracted FITS/PNG.
  - Column customizer to dynamically show/hide table columns.
  - Fast pagination (10, 25, 50, 100 per page).
- 🌌 **Mollweide All-Sky Celestial Map & Spatial Viewport Filtering**
  - Fixed 2:1 aspect ratio Mollweide all-sky projection with East-to-left astronomical convention.
  - **Central Meridian (RA) Rotation**: Interactive slider ($0^\circ \sim 360^\circ$) and quick presets ($0^\circ, 60^\circ, 120^\circ, 180^\circ, 240^\circ, 300^\circ$) to center any sky area.
  - **"Filter Table by View"**: Zoom/pan to any sky field and click to spatially filter table targets to the visible celestial bounding box with an on-map overlay.
  - **Dual Scope & Focus Rings**: Toggle between `📄 Page` and `🌐 All Filtered` (full 200k+ survey rendered via WebGL `scattergl` with active page targets highlighted by white focus rings).
  - **Dataset-Tied Fast Coordinates Cache**: Automatically saves and loads compressed coordinate cache (`.{dbname}_sky_cache.json.gz`) in the dataset's directory, enabling sub-2ms startup and zero-lag HTTP ETag (304) / GZip transfer.
- 💻 **Advanced SQL Query Mode & Schema Explorer**
  - Dedicated SQL Query Editor tab alongside standard filters.
  - Interactive Schema Explorer showing tables, views, column types, and row counts.
  - **Custom Astronomical SQL Functions**:
    - `CONE_SEARCH(ra, dec, center_ra, center_dec, radius_arcsec)`: Circular cone search
    - `BOX_SEARCH(ra, dec, ra_min, ra_max, dec_min, dec_max)`: Rectangular boundary search
    - Math functions: `SQRT`, `POW`, `COS`, `SIN`, `RADIANS`, `DEGREES`, `LOG10`, `LN`, `EXP` directly inside queries.
  - Astronomical SQL presets for one-click query composition.
  - Dynamic table column mapping: Any custom column selected in SQL (e.g. `ts.combination`, `lm.lineFlux`) is rendered as a dedicated column.
- 🌌 **Multi-Wavelength Optical Cutout Viewer (HSC & Pan-STARRS)**
  - Automatically fetches and displays 3-color optical cutouts from Hyper Suprime-Cam (HSC) SSP.
  - Intelligent fallback: Automatically detects missing HSC coverage or blank/white dummy frames and falls back to Pan-STARRS1 (PS1) color cutouts.
- 🖼️ **PNG Spectrum Quick-Look & Sequential Browsing**
  - Instant high-res spectrum modal launched from table thumbnails or celestial map markers.
  - Slide through targets effortlessly with keyboard arrow keys (`←` / `→`) or floating navigation buttons (`❮` / `❯`) without closing the modal.
  - Automatic pagination advance when navigating past page boundaries.
  - Synchronized table row highlighting and one-click jump to the interactive Plotly viewer with preserved redshift.
- 📊 **Deep Parameter Inspection (`📋 Details`)**
  - Solver status, warnings, and error flags (`solver_results`).
  - Model candidate rankings (`redshift_candidates`: Rank, $z$, error, proba, reduced $\chi^2$, $p$-value, template).
  - Detected line measurements (`line_measurements`: Line name, rest wavelength, $z$, flux, EW, $\sigma$).
- 📈 **Interactive FITS Spectrum Viewer (`📈 Plot`)**
  - Pure Astropy FITS reader parsing `WAVELENGTH`, `FLUX`, `COVAR`, and `MASK` directly with Plotly.js rendering.
  - Client-side dynamic inverse-variance binning (Raw, 0.2 nm, 0.5 nm, 1.0 nm, 2.0 nm).
  - $1\sigma$ noise band and bad pixel mask shading.
  - Rest-frame line overlays pinned to paper coordinates during zoom/pan:
    - **Emission lines**: Lyα, C IV, C III], Mg II, [O II], Hβ, [O III], Hα, [N II], [S II]
    - **Absorption lines**: Ca II H/K, G-band, Mg b, Na D
  - **Real-Time Redshift Slider**: Drag to dynamically shift line overlays for visual redshift confirmation.
  - Individual exposure breakdown (Visits, arms, spectrographs, exposure times).
  - One-click raw FITS and PNG downloads.

---

## ディレクトリ構成

```text
pfs_target_viewer/
├── app.py                 # FastAPI バックエンドサーバー
├── requirements.txt       # 依存ライブラリ一覧
├── run_viewer.sh          # ワンクリック起動スクリプト (venv自動構築)
├── README.md              # 本ドキュメント
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
cd /mnt/ugnas/work/LSST/PFS/pfs_target_viewer
./run_viewer.sh
```

ポート番号やホストを変更したい場合：
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

### 方法 3: `uv` を使用した超高速セットアップ

`uv` がインストールされている環境では、わずか数秒でセットアップできます：

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

### 2. リモートサーバー（例: `pgx` などの計算機）で動かしている場合
お使いのローカル PC から SSH ポートフォワーディングで接続します：

```bash
# ローカル PC のターミナルで実行
ssh -L 8090:localhost:8090 yasuda@<remote-host>
```
接続後、ローカル PC のブラウザで `http://localhost:8090` を開いてください。

---

## Command Line Arguments & Data Directory

You can directly specify the directory containing `pfs_metadata.sqlite3` and `extracted_targets/` when starting the server:

```bash
# Method 1: Specify directory as a positional argument (Recommended)
./run_viewer.sh /path/to/dataset
python app.py /path/to/dataset

# Method 2: Specify directory via --dir (-d)
./run_viewer.sh --dir /path/to/dataset
python app.py -d /path/to/dataset

# Method 3: Specify directory via environment variable
export PFS_DIR=/path/to/dataset
./run_viewer.sh
```

### Argument List

```bash
python app.py [-h] [-d OPT_DIR] [-c CONFIG] [--host HOST] [--port PORT] [--db DB] [--data-dir DATA_DIR] [target_dir]
```

- `target_dir` (positional): Path to directory containing `pfs_metadata.sqlite3` and `extracted_targets/` (default: `..`)
- `-d, --dir, --dataset-dir`: Path to directory containing `pfs_metadata.sqlite3` and `extracted_targets/`
- `-c, --config`: Datasets config file (see below; defaults to `datasets.toml` next to `app.py` if it exists)
- `--host`: Host interface to bind (default: `0.0.0.0`)
- `--port`: Port to listen on (default: `8090`)
- `--db`: Explicit path to SQLite database (overrides `--dir`)
- `--data-dir`: Explicit path to `extracted_targets` directory (overrides `--dir`)
- `--security-log`: Security log for fail2ban (see below; `none` disables)

---

## Multiple Datasets (Config File)

Register several datasets in `datasets.toml` and the browser shows a dataset selection page on access. Each dataset can optionally be protected by a password.

```bash
cp datasets.example.toml datasets.toml   # loaded automatically when placed next to app.py
vi datasets.toml
./run_viewer.sh

# Or use a config file elsewhere:
./run_viewer.sh --config /path/to/datasets.toml
```

```toml
[[datasets]]
id = "s26b047-ql"                              # ID used in URLs (?ds=...); derived from name if omitted
name = "S26B-047 QL"
description = "Quick-look reduction (run31)"
dir = "/mnt/ugnas/work/LSST/PFS/S26B-047/QL"   # directory with pfs_metadata.sqlite3 and extracted_targets/
password = "secret"                            # omit for a dataset open to everyone

[[datasets]]
name = "S26A-104"
db = "/path/to/pfs_metadata.sqlite3"           # db / data_dir can be given instead of dir
data_dir = "/path/to/extracted_targets"
```

- The selection page is `/datasets`. While browsing, the **⇄ Switch** button in the header returns to it.
- The selected dataset and entered passwords are kept per browser (7 days by default; `session_days`). Several people can browse different datasets at the same time, and tabs of the same browser showing different datasets do not interfere.
- `datasets.toml` is reloaded automatically when it changes (no restart needed). Changing a password invalidates existing logins to that dataset.
- Passwords are stored in plain text, so `datasets.toml` is git-ignored; mind its file permissions.
- Without `secret_key`, a random key is generated at each server start, so passwords must be entered again after a restart.
- A dataset given with `--dir` etc. is listed first, in addition to the config datasets. With a single dataset without a password, the viewer opens directly without the selection page, as before.


---

## Blocking Malicious Access (fail2ban)

On a publicly reachable machine, fail2ban can block vulnerability scanners and similar clients at the firewall.

The viewer writes one line per suspicious request, with the client IP, to a security log (default `~/.local/state/pfs-target-viewer/security.log`; change with `--security-log PATH`, disable with `--security-log none`). Keep it on a local disk: fail2ban runs as root, which often cannot read NFS-mounted files.

| event | Meaning | Banned by default |
|---|---|---|
| `not_found` | URL the viewer does not have (`/wp-login.php`, `/.env`, ...) | ✅ |
| `bad_password` | Wrong dataset password | ✅ |
| `method_not_allowed` | Wrong HTTP method | ✅ |
| `unauthorized` | API access without selecting a dataset (also legitimate browsers with an expired session) | ❌ (logged only) |

404s for missing spectra/FITS of real targets and browser requests such as `/favicon.ico` are not logged.

### Setup (requires root)

```bash
sudo apt install fail2ban
sudo cp fail2ban/filter.d/pfs-viewer.conf /etc/fail2ban/filter.d/
sudo cp fail2ban/jail.d/pfs-viewer.local  /etc/fail2ban/jail.d/
sudo vi /etc/fail2ban/jail.d/pfs-viewer.local   # check logpath, port and ignoreip
sudo systemctl enable --now fail2ban

# Check that the filter matches the log
sudo fail2ban-regex ~/.local/state/pfs-target-viewer/security.log /etc/fail2ban/filter.d/pfs-viewer.conf
```

By default an address with 5 suspicious requests within 10 minutes is banned for 1 hour; repeat offenders are banned longer (up to 1 week). `127.0.0.1` and `192.168.0.0/16` (LAN) are never banned.

```bash
sudo fail2ban-client status pfs-viewer               # list banned addresses
sudo fail2ban-client set pfs-viewer unbanip 1.2.3.4  # unban
```

---

## 画面の主な使い方

1. **クイック統計バッジ（画面最上部）**
   - リポジトリ内の総天体数、および Galaxy / QSO / Star の内訳を表示します。
2. **検索 & フィルターバー**
   - **Search**: `rubin_0001` や `313875415099768848` などの obCode または Target ID で即座に検索できます。
   - **Class**: `All`, `Galaxy`, `QSO`, `Star` のピルボタンで分類別にワンクリック抽出。
   - **Redshift**: 最小 $z$ と最大 $z$ を入力して赤方偏移の範囲指定検索（例: $z \ge 6.0$）。
   - **Sort**: 赤方偏移の高い順、低い順、Target ID 順、各分類確率順等でソート。
3. **ターゲット一覧テーブル**
   - サムネイル画像をクリックすると、高解像度の PNG プロットがモーダルで拡大表示されます。
   - 各行の **「📋 Details」** ボタンをクリックすると、ソルバー結果、全候補解、輝線・吸収線の測定パラメータがタブ形式で表示されます。
   - **「📈 Plot」** ボタンをクリックすると、FITS 生データを読み込んでインタラクティブなスペクトルビューアが起動します。
   - **「💾 FITS」** ボタンから生 FITS ファイルを直接ダウンロード可能です。
4. **インタラクティブ・スペクトルビューア**
   - **ズーム / パン**: グラフ上をドラッグして任意の波長領域を拡大・観察できます（ダブルクリックでリセット）。
   - **Binning**: プルダウンでビン幅（Raw, 0.2 nm, 0.5 nm, 1.0 nm, 2.0 nm）を動的に切り替えます。
   - **Lines**: チェックボックスで輝線（青）や吸収線（赤）の表示をオン/オフできます。
   - **Adjust $z$**: スライダーまたは数値入力で赤方偏移を変更すると、輝線・吸収線の縦線がリアルタイムで追従します。
