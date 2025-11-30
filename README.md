# Timezone Tracker for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

A Home Assistant custom component that tracks your location relative to timezone boundaries and automatically updates Home Assistant's timezone when you cross one. Perfect for RVs, vans, boats, and anyone on the move.

## Features

- **100% Local**: Uses locally stored timezone boundary polygons - no API calls for timezone lookups
- **Accurate Boundaries**: Real timezone boundaries from OpenStreetMap, not simplified longitude lines
- **Smart Boundary Detection**: Only considers boundaries between actual timezones, ignoring coastal edges and ocean boundaries
- **Adaptive Polling**: Checks frequently when near a boundary, infrequently when far away
- **Heading-Aware**: Calculates distance along your direction of travel
- **Hysteresis**: Prevents timezone flip-flopping due to GPS jitter at boundaries
- **UI Configuration**: Full config flow support - no YAML editing required

## How It Works

```
GPS Update → Local Polygon Lookup → Distance to Adjacent Timezone → Adaptive Interval → Auto-Update HA Timezone
```

1. Reads your GPS coordinates from a device tracker entity
2. Performs point-in-polygon lookup against locally stored timezone boundaries
3. Calculates distance to the nearest *adjacent timezone* (not coastal/ocean edges)
4. Also calculates distance along your heading to the next timezone
5. Sets polling interval based on distance and speed
6. Updates Home Assistant's timezone when you cross a boundary

### Smart Boundary Detection

The integration intelligently ignores boundaries that don't lead to a different timezone. For example:

- If you're in California (Pacific time), it measures distance to the Mountain timezone boundary to the east, **not** the edge of the Pacific timezone polygon in the ocean
- When calculating distance along your heading, it only reports a boundary if crossing it would put you in a different timezone

This ensures you get accurate, meaningful distance readings regardless of your proximity to coastlines or other non-timezone boundaries.

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots in the top right → **Custom repositories**
3. Add this repository URL with category **Integration**
4. Click **Install**
5. Restart Home Assistant

### Manual Installation

1. Download the `custom_components/timezone_tracker` folder
2. Copy it to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

## Setup

### Step 1: Install the Integration

#### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots in the top right → **Custom repositories**
3. Add this repository URL with category **Integration**
4. Click **Install**
5. Restart Home Assistant

#### Manual Installation

1. Download the `custom_components/timezone_tracker` folder
2. Copy it to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

### Step 2: Add the Integration

1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration**
3. Search for **Timezone Tracker**
4. Select your GPS device tracker entity
5. Choose a region filter (affects download size and memory):
   - **All Timezones** (~120MB) - Full worldwide coverage
   - **North America** (~8MB) - US, Canada, Mexico
   - **US & Canada** (~6MB)
   - **United States only** (~3MB)
   - **Europe** (~5MB)
   - **All Americas** (~15MB)
6. Click **Submit**

The integration will automatically download the timezone boundary data for your selected region on first run.

## Configuration Options

After setup, you can adjust options by clicking **Configure** on the integration:

| Option | Default | Description |
|--------|---------|-------------|
| Region | North America | Geographic region for timezone data (changing triggers automatic re-download) |
| Min Interval | 30s | Minimum time between checks (when very close to boundary) |
| Max Interval | 3600s | Maximum time between checks (when far from any boundary) |
| Hysteresis Count | 2 | Consecutive readings in new timezone required before switching |

**Changing the region:** When you select a new region, the integration immediately starts downloading the new dataset in the background. You'll see log entries showing the download progress. The integration continues working with cached data until the new download completes.

## Sensors

The integration creates three sensors:

### Boundary Distance (`sensor.timezone_tracker_boundary_distance`)
- **State**: Distance to nearest timezone boundary in miles
- **Attributes**:
  - `edge_distance`: Straight-line distance to nearest adjacent timezone
  - `heading_distance`: Distance along current heading to next timezone
  - `nearest_timezone`: The timezone that is nearest to your current location (e.g., `America/Denver`)
  - `latitude`, `longitude`, `heading`, `speed`: Current GPS state

### Current Timezone (`sensor.timezone_tracker_current_timezone`)
- **State**: Current timezone (e.g., `America/Los_Angeles`)
- **Attributes**:
  - `detected_timezone`: What the boundary data shows
  - `pending_change`: Timezone waiting for confirmation (if any)
  - `pending_count`: Confirmation count (toward hysteresis threshold)

### Check Interval (`sensor.timezone_tracker_check_interval`)
- **State**: Current polling interval in seconds
- **Attributes**:
  - `distance_category`: very_close, close, medium, far, very_far
  - `speed_category`: stopped, slow, normal, fast
  - `interval_minutes`: Interval in minutes

## Polling Behavior

| Distance | Speed | Interval |
|----------|-------|----------|
| < 2 mi | Moving | ~30 sec |
| < 6 mi | Fast (> 65 mph) | ~1-2 min |
| < 6 mi | Normal | ~3-5 min |
| 6-20 mi | Any | ~5-15 min |
| 20-50 mi | Any | ~15-30 min |
| > 50 mi | Any | ~30-60 min |
| Any | Stopped | ~60 min |

## Services

### `timezone_tracker.force_update`
Force an immediate timezone check, ignoring the scheduled interval.

### `timezone_tracker.reload_data`
Reload timezone boundary data from the cached GeoJSON file.

### `timezone_tracker.download_data`
Delete the cached data and re-download timezone boundaries from the internet. Uses the region filter configured in the integration options. Useful if the boundary data has been updated upstream.

## Dashboard Card Example

```yaml
type: entities
title: Timezone Tracker
entities:
  - entity: sensor.timezone_tracker_current_timezone
    name: Current Timezone
  - entity: sensor.timezone_tracker_boundary_distance
    name: Distance to Boundary
    secondary_info: attribute
    attribute: nearest_timezone
  - entity: sensor.timezone_tracker_check_interval
    name: Check Interval
    secondary_info: attribute
    attribute: interval_minutes
```

## Troubleshooting

### "Failed to download timezone data"
Check your internet connection. The integration downloads data from GitHub on first run. If you're behind a firewall, you may need to allow access to `github.com`.

### "shapely not installed"
The dependencies should install automatically. If not, try:
```bash
# For HA Container:
docker exec -it homeassistant pip install shapely ijson

# Then restart Home Assistant
```

### Timezone not updating
1. Check the logs for errors (Settings → System → Logs)
2. Verify your GPS entity has `latitude` and `longitude` attributes
3. Try the `timezone_tracker.force_update` service
4. Increase the hysteresis count if you're getting flip-flopping at boundaries

### High memory usage / Out of Memory on Raspberry Pi
The "All Timezones" region requires ~500MB+ of RAM and is **not recommended for Raspberry Pi** or other low-memory devices.

**Estimated RAM usage by region:**
| Region | Disk Size | RAM Usage |
|--------|-----------|-----------|
| US only | ~3MB | ~50MB |
| Europe | ~5MB | ~80MB |
| US & Canada | ~6MB | ~90MB |
| North America | ~8MB | ~100MB |
| All Americas | ~15MB | ~150MB |
| All Timezones | ~120MB | ~500MB+ |

If you're experiencing OOM (Out of Memory) crashes:
1. Go to **Settings** → **Devices & Services**
2. Find **Timezone Tracker** and click **Configure**
3. Select a smaller region (e.g., "North America" instead of "All")
4. Click **Submit** - the data will be re-downloaded with the new filter

### Slow first startup
The first run downloads and processes boundary data. The time depends on your selected region:
- US only: ~3MB, fast
- North America: ~8MB, quick  
- All timezones: ~120MB, slower (and high memory usage!)

Subsequent startups load from the cached file and are much faster.

### Need to change region after setup
You can change the region in the integration options:
1. Go to **Settings** → **Devices & Services**
2. Find **Timezone Tracker** and click **Configure**
3. Select a new region from the dropdown
4. Click **Submit**

The new timezone data will begin downloading immediately in the background. Check the logs to monitor progress. The integration continues working until the download completes and the new data is loaded.

Alternatively, you can call the `timezone_tracker.download_data` service to force a re-download with the current region settings.

## Technical Details

### Data Storage
Timezone boundary data is stored in `.storage/timezone_tracker/` within your Home Assistant config directory. This location:
- Keeps data out of your main config directory
- Is typically excluded from Home Assistant backups (avoiding backup bloat)
- Persists across container restarts

### Performance
- **Spatial indexing**: Uses R-tree (STRtree) for O(log N) polygon queries instead of O(N) iteration
- **Streaming JSON**: Uses `ijson` for memory-efficient parsing of large GeoJSON files
- **Streaming downloads**: Downloads are streamed to disk rather than loaded into RAM

### Dependencies
- `shapely>=2.0.0` - Polygon geometry operations
- `ijson>=3.0.0` - Memory-efficient JSON streaming (optional but recommended)

## Data Source

Timezone boundaries are from [timezone-boundary-builder](https://github.com/evansiroky/timezone-boundary-builder), which sources data from OpenStreetMap. The data is released regularly when timezone boundaries change.

To update to the latest boundary data, call the `timezone_tracker.download_data` service or change the region in the integration options.

## License

MIT License - See LICENSE file for details.

The timezone boundary data is from OpenStreetMap contributors and is available under the ODbL license.

## Credits

- [timezone-boundary-builder](https://github.com/evansiroky/timezone-boundary-builder) for the boundary data
- Inspired by [hass-timezone-setter](https://github.com/SmartyVan/hass-timezone-setter) and [hass-geolocator](https://github.com/SmartyVan/hass-geolocator)
