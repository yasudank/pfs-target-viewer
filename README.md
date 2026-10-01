**English** | [日本語](README_ja.md)

---

# PFS Target & Spectrum Viewer

An integrated toolkit for aggregating Subaru Prime Focus Spectrograph (PFS) coadd observation metadata into an SQLite database, extracting target raw spectra (`pfsObject` FITS) and diagnostic plots (PNG), and interactively exploring targets via a standalone web application.

---

## 📁 Repository Structure

```text
pfs-target-viewer/
├── .gitignore
├── README.md                      # Project Guide (English)
├── README_ja.md                   # Project Guide (Japanese)
├── download_data.sh               # Hugging Face dataset download script (Bash)
├── download_data.py               # Hugging Face dataset download script (Python)
├── build_pfs_database.py          # [Step 1] Build SQLite DB from pfsConfig & pfsCoZCandidates
├── export_pfs_targets.py          # [Step 2] Extract per-target pfsObject FITS and PNG plots
├── run_pfs.py                     # PFS pipeline execution wrapper
└── pfs_target_viewer/             # [Step 3] Standalone Web Application
    ├── README.md                  # Viewer Manual (English)
    ├── README_ja.md               # Viewer Manual (Japanese)
    ├── app.py                     # FastAPI backend server & FITS/SQLite parser
    ├── requirements.txt           # Viewer dependencies (Pipeline-independent)
    ├── run_viewer.sh              # One-click launcher (auto-creates venv)
    ├── templates/
    │   └── index.html             # Dashboard UI template
    └── static/
        ├── css/
        │   └── style.css          # Dark-themed astronomical UI styling
        └── js/
            ├── app.js             # Client-side state, dynamic binning & Plotly logic
            └── plotly.min.js      # Offline standalone Plotly.js bundle
```

---

## 🚀 Workflow Overview

This toolkit provides an end-to-end data pipeline and interactive inspection workflow:

```text
[PFS Butler Repository]
       │
       ▼  (python run_pfs.py build_pfs_database.py)
[pfs_metadata.sqlite3]  ─── Aggregated metadata for 13,000+ targets
       │
       ▼  (python run_pfs.py export_pfs_targets.py)
[extracted_targets/]    ─── fits/ (pfsObject raw data) & png/ (spectrum plots)
       │
       ▼  (cd pfs_target_viewer && ./run_viewer.sh)
[Web Dashboard (http://localhost:8090)] ─── Search, deep inspection & interactive Plotly plots
```

---

### Step 1: Metadata Database Ingestion (`build_pfs_database.py`)

Reads `pfsConfig` and `pfsCoZCandidates` from the PFS Gen3 Butler repository and ingests target summaries, solver results, candidate models, and line measurements into SQLite (`pfs_metadata.sqlite3`).

```bash
# Execute within PFS pipeline environment
python run_pfs.py build_pfs_database.py
```

- **Output**: `pfs_metadata.sqlite3`
- **Primary Tables**:
  - `v_target_summary`: Target representative parameters (redshift, classification probabilities, coordinates, obCode, etc.)
  - `solver_results`: Solver status, warning flags (`zWarning`), and error codes
  - `redshift_candidates`: Candidate model rankings, redshifts, $\chi^2$, and templates
  - `line_measurements`: Detected emission and absorption lines (wavelength, flux, EW, $\sigma$)

---

### Step 2: Target FITS & PNG Plot Extraction (`export_pfs_targets.py`)

Extracts raw spectra (`pfsObject` FITS) and generates quick-look spectrum plots (PNG) with rest-frame emission/absorption line overlays for all targets registered in the database.

```bash
# Execute within PFS pipeline environment
python run_pfs.py export_pfs_targets.py
```

- **Output**: `extracted_targets/`
  - `fits/pfsObject_{obCode}_{catId}_{objId}.fits` (Raw spectrum FITS files)
  - `png/spec_{obCode}_{catId}_{objId}.png` (Quick-look spectrum plots)

---

### 📥 For Collaborators: Download Pre-built Datasets (`download_data.sh`)

If you are a collaborator or running on a machine **without the PFS pipeline installed**, you do **not** need to run Step 1 and Step 2. You can download the pre-generated dataset (`pfs_metadata.sqlite3` and `extracted_targets.tar.gz`) directly from the Hugging Face private repository.

> **Zero Host Pollution**: The download script automatically creates the project's dedicated virtual environment (`pfs_target_viewer/.venv_viewer`) and installs `huggingface_hub` and all other viewer dependencies inside it. Your host/system Python environment is **never modified**.

> [!IMPORTANT]
> **Data Transfer Volume & Disk Space Requirements**:
> - **Download Size**: ~**8.0 GB** (`pfs_metadata.sqlite3` 157 MB + `extracted_targets.tar.gz` 7.8 GB)
> - **Extracted Size**: ~**11.2 GB** (`fits/`: 7.6 GB, `png/`: 3.5 GB, database: 157 MB)
> - **Recommended Free Disk Space**: **At least 20 GB**  
>   *(Both the compressed archive and the extracted raw files will temporarily coexist during extraction. Once extraction is complete, you can safely delete `extracted_targets.tar.gz` to reclaim 7.8 GB of disk space.)*
> - **Network**: A fast and stable broadband internet connection is recommended.

```bash
# Set your Hugging Face Access Token (Read permission) and run:
export HF_TOKEN="hf_xxxxxxxxxxxx"
./download_data.sh

# Or using Python:
python download_data.py
```

---

### Step 3: Launch Web Viewer (`pfs_target_viewer/`)

The web application is **completely independent of the PFS pipeline (`pfs_pipe2d`, `lsst-scipipe`)**. It runs on a standard Python 3.10+ environment (FastAPI, Astropy, NumPy, Jinja2) and can be easily reproduced on any machine (laptop, workstation, or server). It is engineered for instant responsiveness even with large-scale catalogs of 200,000+ targets.

```bash
cd pfs_target_viewer
./run_viewer.sh

# If pfs_metadata.sqlite3 and extracted_targets/ are in a different directory:
./run_viewer.sh /path/to/dataset
```

Then open `http://localhost:8090` in your web browser.

---

## ✨ Key Features & Capabilities

### 1. High-Performance Search, Filter & Server-Side Query Caching
- **Full-Dataset Instant Sorting & Pagination**:
  - Powered by a server-side in-memory query cache (`SQL_CACHE`), multi-column sorting (Redshift, Velocity $v = c \cdot z$, Target ID, `catId`, classification probabilities) operates across the **entire dataset of matching targets (tens of thousands to 200k+) in sub-milliseconds**.
  - Unlike single-page sorting, pagination (10, 25, 50, 100 per page) reflects true global ordering across all pages.
- **Versatile Filter Toolbar**:
  - Real-time search by `obCode` (substring) or 64-bit `objId` (exact match).
  - Catalog ID (`catId`) dropdown with per-catalog target count badges.
  - Classification filter pills (`ALL`, `GALAXY`, `QSO`, `STAR`).
  - Redshift range filtering ($z_{min} \le z \le z_{max}$, e.g. $z \ge 6.0$).
  - "With Spectra" checkbox to quickly isolate targets with extracted FITS/PNG.
  - Column customizer to dynamically show or hide table columns.

### 2. Mollweide All-Sky Celestial Map & Spatial Viewport Filtering
- **Mollweide Projection with Fixed 2:1 Aspect Ratio**:
  - Displays Right Ascension (RA) and Declination (Dec) projected onto an elliptical all-sky Mollweide map following astronomical convention (East to the left).
  - Maintains true 2:1 aspect ratio during zooming and panning.
- **Central Meridian (RA) Rotation Controls**:
  - Interactive slider ($0^\circ \sim 360^\circ$) and quick preset buttons ($0^\circ, 60^\circ, 120^\circ, 180^\circ, 240^\circ, 300^\circ$) to center the sky view on your survey field.
- **Dual Scope & Page Focus Rings**:
  - Toggle between `📄 Page` (current table page targets) and `🌐 All Filtered` (all matching targets across survey, rendered smoothly via WebGL `scattergl` without arbitrary row limits). Active table targets are emphasized with white focus rings.
- **"Filter Table by View" Spatial Filtering**:
  - Pan/zoom to any celestial region of interest and click **"Filter Table by View"** to dynamically restrict the table to targets within the visible sky bounding box (with an on-map viewport bounding box overlay).
- **Dataset-Tied Fast Celestial Coordinate Cache**:
  - On startup or dataset switch, celestial coordinates are generated and stored in a compressed disk cache (`.{dbname}_sky_cache.json.gz`) directly in the dataset's directory.
  - Subsequent launches and page loads retrieve the full-sky coordinate catalog in ~2ms from memory or disk, accelerated by HTTP ETag (304 Not Modified) and GZip compression.

### 3. Advanced SQL Query Mode & Schema Explorer
- **Interactive In-Browser SQL Query Editor**:
  - Switch freely between Standard Filters and a dedicated SQL Query Editor.
  - Resizable editor aligned with the interactive Schema Explorer (browsing tables, views, column data types, and row counts).
- **Custom Astronomical SQL Functions**:
  - `CONE_SEARCH(ra, dec, center_ra, center_dec, radius_arcsec)`: Fast circular aperture cone search
  - `BOX_SEARCH(ra, dec, ra_min, ra_max, dec_min, dec_max)`: Rectangular boundary search
  - Math extensions: `SQRT`, `POW`, `COS`, `SIN`, `RADIANS`, `DEGREES`, `LOG10`, `LN`, `EXP` directly within SQLite queries.
- **Astronomical SQL Presets**:
  - One-click template queries for Cone searches, high-$z$ quasars, emission line flux rankings, solver warnings, and more.
- **Dynamic Table Column Mapping**:
  - Any custom column selected in SQL (e.g., `ts.combination`, `lm.lineFlux`, `lm.lineEW`, or joined tables) is automatically extracted and displayed as a dedicated column in the results table.

### 4. Multi-Wavelength Optical Cutout Imaging (HSC & Pan-STARRS)
- **Direct Optical Context**:
  - Deep inspection modal automatically fetches and displays 3-color optical cutouts from Hyper Suprime-Cam (HSC) Subaru Strategic Program (SSP).
  - **Intelligent Fallback**: Detects missing HSC coverage or blank/white dummy frames and automatically falls back to Pan-STARRS1 (PS1) color cutouts.

### 5. PNG Quick-Look & Sequential Browsing
- **Effortless Target Inspection**:
  - Launch high-resolution PNG spectrum plots directly from table thumbnails or celestial map markers.
  - Slide through targets effortlessly using keyboard arrow keys (`←` / `→`) or floating navigation buttons (`❮` / `❯`) without closing the modal.
  - Automatically fetches the next page when crossing page boundaries.
  - Synchronized table row highlighting and one-click jump to the interactive Plotly viewer with preserved redshift.

### 6. Deep Parameter Inspection (`📋 Details`)
- **Comprehensive Pipeline Diagnostics**:
  - Model candidate rankings (`redshift_candidates`: Rank, $z$, error, proba, reduced $\chi^2$, $p$-value, template).
  - Detected line measurements (`line_measurements`: Line name, rest wavelength, $z$, flux, EW, $\sigma$).
  - Solver execution flags and warnings (`solver_results`).

### 7. Interactive FITS Spectrum Viewer (`📈 Plot`)
- **Precision Plotly.js Analysis**:
  - Direct FITS reader parsing `WAVELENGTH`, `FLUX`, `COVAR`, and `MASK`.
  - Client-side dynamic inverse-variance binning (Raw, 0.2 nm, 0.5 nm, 1.0 nm, 2.0 nm).
  - $1\sigma$ noise band and bad pixel mask shading.
  - Rest-frame line overlays pinned to paper coordinates during zoom/pan:
    - **Emission lines**: Lyα, C IV, C III], Mg II, [O II], Hβ, [O III], Hα, [N II], [S II]
    - **Absorption lines**: Ca II H/K, G-band, Mg b, Na D
  - **Real-Time Redshift Slider**: Drag to dynamically shift line overlays for visual redshift confirmation.
  - Individual exposure breakdown (Visits, arms, spectrographs, exposure times).
  - One-click raw FITS and PNG downloads.

### 8. Scalable Architecture for Large Datasets (Phase 2 Sharding)
- **Built for 200,000+ Targets**:
  - Supports directory sharding (`fits/NNN/`, `png/NNN/`) to bypass OS-level single-directory entry limits.
  - Automatically discovers file locations using database-backed path indices (`target_files` table), sharded directories, or legacy flat structures.

---

## 🛠️ Requirements

- **Step 1 & 2 (Data Ingestion & Extraction)**:
  - PFS 2D Pipeline environment (`pfs_pipe2d`, `lsst-scipipe`)
- **Step 3 (Web Viewer)**:
  - Python 3.10+
  - Dependencies: `fastapi`, `uvicorn`, `astropy`, `numpy`, `jinja2`, `python-multipart`
  - *Note: Running `./run_viewer.sh` automatically sets up the dedicated `.venv_viewer` virtual environment.*

---

## 📄 License

This software is developed for research and academic purposes within the Subaru Prime Focus Spectrograph collaboration.
