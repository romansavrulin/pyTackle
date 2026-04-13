# ZfsIotop

Visualize ZFS I/O statistics using an interactive Dash dashboard.

## Overview

**ZfsIotop** is a tackle for visualizing ZFS pool I/O statistics. It imports CSV data from `zpool iostat` output into a SQLite database and displays interactive time-series charts using Plotly and Dash.

### Key Features

- **CSV import** — Import `zpool iostat` output into SQLite for analysis
- **Interactive dashboard** — Web-based visualization using Dash and Plotly
- **Time aggregation** — Configurable bucket sizes for data aggregation
- **Multi-pool support** — Visualize multiple ZFS pools simultaneously
- **Logarithmic scale** — Log-scale Y-axis for wide-ranging I/O values

## Prerequisites

### Python Dependencies

```bash
pip install pandas plotly dash sqlalchemy
```

### Data Collection

Collect ZFS I/O statistics using `zpool iostat` with CSV output:

```bash
# Example: Collect stats every second, output as CSV
zpool iostat -p -H -l 1 > out.dat
```

The expected CSV format includes columns for:
- `record_number` — Sequential record number
- `pool_device` — ZFS pool name
- Operation columns (e.g., `operations_read`, `operations_write`, `bandwidth_read`, `bandwidth_write`)

## Usage

```bash
pyTackle ZfsIotop [OPTIONS]
```

## CLI Reference

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--db PATH` | `dat.db` | Path to SQLite database file |
| `--seconds N` | `60` | Aggregation bucket size in seconds |
| `--pools POOL [POOL ...]` | `pvdata rpool` | ZFS pool devices to include |
| `--port PORT` | `8050` | Port for the Dash server |
| `--convert` | - | Import CSV data into the database before visualizing |
| `--csv PATH` | `out.dat` | Path to CSV file used with `--convert` |

## Examples

### Import and Visualize

Import CSV data into the database and start the dashboard:

```bash
pyTackle ZfsIotop --convert --csv zpool_stats.csv --db zfs_stats.db
```

### Visualize Existing Database

If data is already imported, just visualize:

```bash
pyTackle ZfsIotop --db zfs_stats.db
```

### Custom Aggregation and Pools

Aggregate data in 5-minute buckets for specific pools:

```bash
pyTackle ZfsIotop \
    --db zfs_stats.db \
    --seconds 300 \
    --pools tank backup
```

### Custom Port

Run the dashboard on a different port:

```bash
pyTackle ZfsIotop --db zfs_stats.db --port 8080
```

## Dashboard

The dashboard is accessible at `http://localhost:8050` (or custom port).

### Visualization

- **X-axis**: Time intervals (aggregated buckets)
- **Y-axis**: I/O values (logarithmic scale)
- **Lines**: Different I/O operations (read/write bandwidth, IOPS)
- **Facets**: Separate row per pool device

### Interactive Features

- Zoom and pan on the chart
- Hover tooltips with exact values
- Click legend items to show/hide operations

## Data Flow

```
1. Collect data     →    2. Import CSV     →    3. Query DB     →    4. Visualize
   (zpool iostat)         (--convert)           (aggregated)        (Dash server)
```

## Database Schema

The `data` table contains:

| Column | Type | Description |
|--------|------|-------------|
| `record_number` | INTEGER | Sequential record from source |
| `CreatedDate` | DATETIME | Timestamp (derived from record_number) |
| `pool_device` | TEXT | ZFS pool name |
| `operation` | TEXT | I/O operation type |
| `value` | REAL | Metric value |

## Platform Support

| Platform | Status |
|----------|--------|
| **Linux** | ✅ Full support (native ZFS) |
| **FreeBSD** | ✅ Full support (native ZFS) |
| **macOS** | ⚠️ Requires OpenZFS |
| **Windows** | ❌ ZFS not available |

## Requirements

- Python 3.8+
- pandas
- plotly
- dash
- sqlalchemy

## See Also

- [pyTackle README](README.md) — Overview of all available tackles
