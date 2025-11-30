#!/usr/bin/env python3
"""
Setup script for Timezone Tracker - Downloads timezone boundary data.

Downloads timezone boundary data from timezone-boundary-builder and optionally
filters it to specific regions to reduce file size.

Usage:
    python setup_timezone_data.py [--filter-regions us,ca,mx] [--output-dir /config/timezone_data]

Requirements:
    pip install requests shapely
"""

import argparse
import json
import os
import sys
import zipfile
from io import BytesIO

try:
    import requests
except ImportError:
    print("Error: requests library required. Install with: pip install requests")
    sys.exit(1)

try:
    from shapely.geometry import shape
except ImportError:
    print("Warning: shapely not installed. Geometry validation will be skipped.")
    shape = None


# Latest release URL from timezone-boundary-builder
TIMEZONE_DATA_URL = "https://github.com/evansiroky/timezone-boundary-builder/releases/latest/download/timezones-now.geojson.zip"

# Timezone prefixes for common regions
REGION_PREFIXES = {
    "us": ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
           "America/Phoenix", "America/Anchorage", "America/Adak", "America/Honolulu",
           "America/Detroit", "America/Kentucky", "America/Indiana", "America/Menominee",
           "America/North_Dakota", "America/Boise", "America/Juneau", "America/Sitka",
           "America/Metlakatla", "America/Yakutat", "America/Nome", "Pacific/Honolulu"],
    "ca": ["America/Toronto", "America/Vancouver", "America/Edmonton", "America/Winnipeg",
           "America/Halifax", "America/St_Johns", "America/Regina", "America/Yellowknife",
           "America/Whitehorse", "America/Iqaluit", "America/Moncton", "America/Goose_Bay",
           "America/Glace_Bay", "America/Blanc-Sablon", "America/Cambridge_Bay",
           "America/Inuvik", "America/Dawson", "America/Creston", "America/Fort_Nelson",
           "America/Rankin_Inlet", "America/Resolute", "America/Atikokan", "America/Pangnirtung",
           "America/Thunder_Bay", "America/Nipigon", "America/Rainy_River", "America/Swift_Current"],
    "mx": ["America/Mexico_City", "America/Cancun", "America/Tijuana", "America/Hermosillo",
           "America/Mazatlan", "America/Chihuahua", "America/Ojinaga", "America/Matamoros",
           "America/Monterrey", "America/Merida", "America/Bahia_Banderas"],
    "eu": ["Europe/"],
    "na": ["America/"],
}


def download_timezone_data(url):
    """Download and extract timezone GeoJSON from zip file."""
    print(f"Downloading timezone data from:\n  {url}")
    print("This may take a minute...")

    response = requests.get(url, stream=True)
    response.raise_for_status()

    total_size = int(response.headers.get('content-length', 0))
    downloaded = 0
    chunks = []

    for chunk in response.iter_content(chunk_size=8192):
        chunks.append(chunk)
        downloaded += len(chunk)
        if total_size:
            pct = (downloaded / total_size) * 100
            print(f"\r  Downloaded: {downloaded / 1024 / 1024:.1f} MB ({pct:.1f}%)", end="")

    print("\n  Download complete!")

    print("  Extracting...")
    zip_data = BytesIO(b''.join(chunks))

    with zipfile.ZipFile(zip_data, 'r') as zf:
        geojson_files = [f for f in zf.namelist() if f.endswith('.geojson') or f.endswith('.json')]
        if not geojson_files:
            raise ValueError("No GeoJSON file found in zip archive")

        geojson_name = geojson_files[0]
        print(f"  Extracting: {geojson_name}")

        with zf.open(geojson_name) as f:
            data = json.load(f)

    print(f"  Loaded {len(data.get('features', []))} timezone boundaries")
    return data


def filter_timezones(data, regions):
    """Filter timezone data to only include specified regions."""
    if not regions:
        return data

    keep_patterns = []
    for region in regions:
        region = region.lower().strip()
        if region in REGION_PREFIXES:
            keep_patterns.extend(REGION_PREFIXES[region])
        else:
            keep_patterns.append(region)

    print(f"Filtering to regions: {regions}")
    original_count = len(data.get('features', []))

    filtered_features = []
    for feature in data.get('features', []):
        tz_id = feature.get('properties', {}).get('tzid', '')

        for pattern in keep_patterns:
            if pattern.endswith('/'):
                if tz_id.startswith(pattern):
                    filtered_features.append(feature)
                    break
            else:
                if tz_id == pattern or tz_id.startswith(pattern + '/'):
                    filtered_features.append(feature)
                    break

    data['features'] = filtered_features
    print(f"  Filtered: {original_count} -> {len(filtered_features)} timezones")
    return data


def validate_geometries(data):
    """Validate and fix any invalid geometries."""
    if shape is None:
        print("Skipping geometry validation (shapely not installed)")
        return data

    print("Validating geometries...")
    fixed_count = 0

    for feature in data.get('features', []):
        try:
            geom = shape(feature['geometry'])
            if not geom.is_valid:
                fixed_geom = geom.buffer(0)
                if fixed_geom.is_valid:
                    feature['geometry'] = json.loads(json.dumps(fixed_geom.__geo_interface__))
                    fixed_count += 1
        except Exception:
            pass

    if fixed_count:
        print(f"  Fixed {fixed_count} invalid geometries")

    return data


def save_data(data, output_path):
    """Save GeoJSON data to file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    print(f"Saving to: {output_path}")

    with open(output_path, 'w') as f:
        json.dump(data, f)

    file_size = os.path.getsize(output_path)
    print(f"  File size: {file_size / 1024 / 1024:.1f} MB")


def main():
    parser = argparse.ArgumentParser(
        description="Download and setup timezone boundary data for Home Assistant"
    )
    parser.add_argument(
        '--filter-regions',
        type=str,
        default=None,
        help='Comma-separated list of regions to include (e.g., "us,ca,mx"). '
             'Available: us, ca, mx, eu, na (all Americas). '
             'Omit to keep all timezones.'
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        default='/config/timezone_data',
        help='Directory to save timezone data (default: /config/timezone_data)'
    )
    parser.add_argument(
        '--no-validate',
        action='store_true',
        help='Skip geometry validation'
    )

    args = parser.parse_args()

    # Download data
    data = download_timezone_data(TIMEZONE_DATA_URL)

    # Filter regions if specified
    if args.filter_regions:
        regions = [r.strip() for r in args.filter_regions.split(',')]
        data = filter_timezones(data, regions)

    # Validate geometries
    if not args.no_validate:
        data = validate_geometries(data)

    # Save
    output_path = os.path.join(args.output_dir, 'timezones.geojson')
    save_data(data, output_path)

    print("\nSetup complete!")
    print(f"\nTimezone data saved to: {output_path}")
    print("You can now configure the Timezone Tracker integration in Home Assistant.")


if __name__ == '__main__':
    main()
