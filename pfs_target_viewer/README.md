**English** | [日本語](README_ja.md)

---

# PFS Target & Spectrum Viewer (Web Application)

A standalone web application for searching, inspecting, and interactively visualizing Subaru Prime Focus Spectrograph (PFS) coadd observation metadata (`pfs_metadata.sqlite3`) and raw spectra (`extracted_targets/` FITS and PNG).

---

## Key Features

- 🚀 **PFS Pipeline Independent (Pipeline-Free)**
  - Operates completely without `lsst-scipipe` or `pfs_pipe2d`, requiring only a standard Python 3.10+ environment (`astropy`, `fastapi`, `uvicorn`, `numpy`, `jinja2`).
  - Readily portable to any machine (personal laptop, analysis workstation, cloud instance) with zero heavy pipeline setup.
- 🔍 **Search, Filter & High-Performance Pagination**
  - Instant search by `obCode` (substring) or `objId` (64-bit ID exact match).
  - Catalog ID (`catId`) dropdown filtering with dynamic target count badges.
  - Target classification filter pills (`GALAXY`, `QSO`, `STAR`).
  - Redshift range filtering ($z_{min} \le z \le z_{max}$, e.g. $z \ge 6.0$).
  - Multi-column sorting by Redshift, Target ID, `catId`, or classification probabilities.
  - Smooth pagination handling 13,000+ targets (10, 25, 50, or 100 targets per page).
- 📊 **Deep Parameter Inspection (`📋 Details`)**
  - Solver status, error codes, and warning flags (`solver_results`).
  - Redshift candidate model rankings (`redshift_candidates`: $z$, error, proba, reduced $\chi^2$, $p$-value, templates).
  - Line measurements (`line_measurements`: rest wavelength, flux, error, EW, $\sigma$).
- 📈 **Interactive FITS Spectrum Viewer (Plotly.js)**
  - Reads raw `pfsObject` FITS arrays (`WAVELENGTH`, `FLUX`, `COVAR`, `MASK`) and renders zoomable/pannable charts with hover tooltips.
  - Dynamic client-side inverse-variance binning (Raw, 0.2 nm, 0.5 nm, 1.0 nm, 2.0 nm).
  - $1\sigma$ noise band and bad pixel mask shading toggles.
  - Emission lines (Lyα, C IV, Mg II, [O II], Ca II H/K, Hβ, [O III], Hα) and absorption lines overlay.
  - **Real-time Redshift Slider**: Shifts line positions smoothly at 60fps for visual redshift verification.
  - Observations exposure table (Visit, arm, spectrograph, fiberId, exposure time).
  - Direct download links for raw FITS files and PNG quick-look plots.

---

## Directory Structure

```text
pfs_target_viewer/
├── app.py                 # FastAPI backend server
├── requirements.txt       # Dependencies
├── run_viewer.sh          # One-click startup script (auto-creates venv)
├── README.md              # Documentation (English)
├── README_ja.md           # Documentation (Japanese)
├── templates/
│   └── index.html         # Dashboard HTML template
└── static/
    ├── css/
    │   └── style.css      # Dark-themed modern CSS
    └── js/
        ├── app.js         # Client-side UI & Plotly logic
        └── plotly.min.js  # Offline standalone Plotly.js bundle
```

---

## Setup & Running

### Method 1: One-Click Launcher (Recommended)

The provided `run_viewer.sh` script automatically creates the virtual environment `.venv_viewer`, installs dependencies, and launches the server.

```bash
cd pfs_target_viewer
./run_viewer.sh
```

To specify a custom port:
```bash
PORT=8088 ./run_viewer.sh
```

---

### Method 2: Manual Setup with `venv` & `pip`

1. **Create and activate virtual environment**:
   ```bash
   cd pfs_target_viewer
   python3 -m venv .venv_viewer
   source .venv_viewer/bin/activate
   ```

2. **Install dependencies**:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. **Start the server**:
   ```bash
   python app.py --port 8090
   ```

---

### Method 3: Ultra-Fast Setup with `uv`

```bash
cd pfs_target_viewer
uv venv .venv_viewer
uv pip install -r requirements.txt --python .venv_viewer
.venv_viewer/bin/python app.py --port 8090
```

---

## Accessing the Dashboard

### 1. Local Machine
Open your web browser and navigate to:
```text
http://localhost:8090
```

### 2. Remote Machine via SSH Port Forwarding
From your local terminal:
```bash
ssh -L 8090:localhost:8090 user@<remote-host>
```
Then open `http://localhost:8090` in your local browser.

---

## Command-Line Arguments

```bash
python app.py [-h] [--host HOST] [--port PORT] [--db DB] [--data-dir DATA_DIR]
```

- `--host`: Host interface to bind (default: `0.0.0.0`)
- `--port`: Port number to listen on (default: `8090`)
- `--db`: Path to `pfs_metadata.sqlite3` (default: `../pfs_metadata.sqlite3`)
- `--data-dir`: Path to `extracted_targets` directory (default: `../extracted_targets`)
