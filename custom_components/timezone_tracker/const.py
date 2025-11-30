"""Constants for the Timezone Tracker integration."""

DOMAIN = "timezone_tracker"

# Configuration
CONF_GPS_ENTITY = "gps_entity"
CONF_MIN_INTERVAL = "min_interval"
CONF_MAX_INTERVAL = "max_interval"
CONF_HYSTERESIS_COUNT = "hysteresis_count"
CONF_REGION_FILTER = "region_filter"

# Storage - relative to .storage directory (not in /config to avoid backup bloat)
STORAGE_DIR = "timezone_tracker"
STORAGE_FILENAME = "timezones.geojson"

# Defaults
DEFAULT_MIN_INTERVAL = 30  # seconds
DEFAULT_MAX_INTERVAL = 3600  # 1 hour
DEFAULT_HYSTERESIS_COUNT = 2  # consecutive readings required
DEFAULT_REGION_FILTER = "north_america"  # Sensible default for most users

# Region filter options (ordered by size, smallest first for better UX)
REGION_FILTERS = {
    "us": "United States only (~3MB, ~50MB RAM)",
    "europe": "Europe (~5MB, ~80MB RAM)",
    "us_canada": "US & Canada (~6MB, ~90MB RAM)",
    "north_america": "North America - US, Canada, Mexico (~8MB, ~100MB RAM)",
    "americas": "All Americas (~15MB, ~150MB RAM)",
    "all": "⚠️ All Timezones (~120MB, ~500MB+ RAM - not for Pi)",
}

# Timezone prefixes for each region
REGION_TIMEZONE_PREFIXES = {
    "all": None,  # No filtering
    "north_america": [
        "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
        "America/Phoenix", "America/Anchorage", "America/Adak", "America/Honolulu",
        "America/Detroit", "America/Kentucky", "America/Indiana", "America/Menominee",
        "America/North_Dakota", "America/Boise", "America/Juneau", "America/Sitka",
        "America/Metlakatla", "America/Yakutat", "America/Nome", "Pacific/Honolulu",
        "America/Toronto", "America/Vancouver", "America/Edmonton", "America/Winnipeg",
        "America/Halifax", "America/St_Johns", "America/Regina", "America/Yellowknife",
        "America/Whitehorse", "America/Iqaluit", "America/Moncton", "America/Goose_Bay",
        "America/Glace_Bay", "America/Blanc-Sablon", "America/Cambridge_Bay",
        "America/Inuvik", "America/Dawson", "America/Creston", "America/Fort_Nelson",
        "America/Rankin_Inlet", "America/Resolute", "America/Atikokan", "America/Pangnirtung",
        "America/Thunder_Bay", "America/Nipigon", "America/Rainy_River", "America/Swift_Current",
        "America/Mexico_City", "America/Cancun", "America/Tijuana", "America/Hermosillo",
        "America/Mazatlan", "America/Chihuahua", "America/Ojinaga", "America/Matamoros",
        "America/Monterrey", "America/Merida", "America/Bahia_Banderas",
    ],
    "us": [
        "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
        "America/Phoenix", "America/Anchorage", "America/Adak", "America/Honolulu",
        "America/Detroit", "America/Kentucky", "America/Indiana", "America/Menominee",
        "America/North_Dakota", "America/Boise", "America/Juneau", "America/Sitka",
        "America/Metlakatla", "America/Yakutat", "America/Nome", "Pacific/Honolulu",
    ],
    "us_canada": [
        "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
        "America/Phoenix", "America/Anchorage", "America/Adak", "America/Honolulu",
        "America/Detroit", "America/Kentucky", "America/Indiana", "America/Menominee",
        "America/North_Dakota", "America/Boise", "America/Juneau", "America/Sitka",
        "America/Metlakatla", "America/Yakutat", "America/Nome", "Pacific/Honolulu",
        "America/Toronto", "America/Vancouver", "America/Edmonton", "America/Winnipeg",
        "America/Halifax", "America/St_Johns", "America/Regina", "America/Yellowknife",
        "America/Whitehorse", "America/Iqaluit", "America/Moncton", "America/Goose_Bay",
        "America/Glace_Bay", "America/Blanc-Sablon", "America/Cambridge_Bay",
        "America/Inuvik", "America/Dawson", "America/Creston", "America/Fort_Nelson",
        "America/Rankin_Inlet", "America/Resolute", "America/Atikokan", "America/Pangnirtung",
        "America/Thunder_Bay", "America/Nipigon", "America/Rainy_River", "America/Swift_Current",
    ],
    "europe": ["Europe/"],
    "americas": ["America/"],
}

# Distance thresholds (miles)
DISTANCE_VERY_CLOSE = 2
DISTANCE_CLOSE = 6
DISTANCE_MEDIUM = 20
DISTANCE_FAR = 50

# Speed thresholds (mph)
SPEED_STOPPED = 3
SPEED_SLOW = 25
SPEED_FAST = 65

# Sensor attributes
ATTR_EDGE_DISTANCE = "edge_distance"
ATTR_HEADING_DISTANCE = "heading_distance"
ATTR_NEAREST_TIMEZONE = "nearest_timezone"
ATTR_DETECTED_TIMEZONE = "detected_timezone"
ATTR_PENDING_CHANGE = "pending_change"
ATTR_PENDING_COUNT = "pending_count"
ATTR_DISTANCE_CATEGORY = "distance_category"
ATTR_SPEED_CATEGORY = "speed_category"
ATTR_INTERVAL_MINUTES = "interval_minutes"
ATTR_LATITUDE = "latitude"
ATTR_LONGITUDE = "longitude"
ATTR_HEADING = "heading"
ATTR_SPEED = "speed"
