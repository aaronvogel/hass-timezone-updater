"""Coordinator for Timezone Tracker."""
from __future__ import annotations

import asyncio
from decimal import Decimal
import json
import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
import zipfile
from io import BytesIO

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DISTANCE_VERY_CLOSE,
    DISTANCE_CLOSE,
    DISTANCE_MEDIUM,
    DISTANCE_FAR,
    SPEED_STOPPED,
    SPEED_SLOW,
    SPEED_FAST,
    REGION_TIMEZONE_PREFIXES,
)

_LOGGER = logging.getLogger(__name__)

# URL for timezone boundary data
TIMEZONE_DATA_URL = "https://github.com/evansiroky/timezone-boundary-builder/releases/latest/download/timezones-now.geojson.zip"

# Earth's radius in miles (for Haversine calculations)
EARTH_RADIUS_MILES = 3958.8

# Try to import shapely
try:
    from shapely.geometry import Point, shape
    from shapely.ops import nearest_points
    from shapely import STRtree
    SHAPELY_AVAILABLE = True
except ImportError:
    SHAPELY_AVAILABLE = False
    _LOGGER.error("shapely not installed. Run: pip install shapely")


@dataclass
class TimezoneData:
    """Data class for timezone tracking state."""
    
    current_timezone: str | None = None
    detected_timezone: str | None = None
    nearest_other_timezone: str | None = None
    edge_distance: float = float('inf')
    heading_distance: float = float('inf')
    effective_distance: float = float('inf')
    pending_timezone: str | None = None
    pending_count: int = 0
    check_interval: int = 3600
    latitude: float = 0.0
    longitude: float = 0.0
    heading: float = 0.0
    speed: float = 0.0
    last_update: datetime | None = None


class TimezoneTrackerCoordinator:
    """Coordinator for timezone tracking."""

    def __init__(
        self,
        hass: HomeAssistant,
        gps_entity: str,
        timezone_data_path: str,
        region_filter: str,
        min_interval: int,
        max_interval: int,
        hysteresis_count: int,
    ) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self.gps_entity = gps_entity
        self.timezone_data_path = timezone_data_path
        self.region_filter = region_filter
        self.min_interval = min_interval
        self.max_interval = max_interval
        self.hysteresis_count = hysteresis_count

        self._tz_polygons: dict[str, Any] = {}
        self._tz_index: list[str] = []  # Maps STRtree index to timezone ID
        self._spatial_tree: STRtree | None = None  # R-tree spatial index
        self._cancel_scheduled: asyncio.TimerHandle | None = None
        self._running = False
        self._listeners: list[callable] = []

        self.data = TimezoneData()

    def async_add_listener(self, listener: callable) -> callable:
        """Add a listener for updates."""
        self._listeners.append(listener)
        
        def remove_listener():
            self._listeners.remove(listener)
        
        return remove_listener

    def _notify_listeners(self) -> None:
        """Notify all listeners of an update."""
        for listener in self._listeners:
            listener()

    async def _async_download_timezone_data(self) -> bool:
        """Download timezone boundary data from GitHub with memory-efficient streaming."""
        try:
            # Ensure directory exists
            data_dir = os.path.dirname(self.timezone_data_path)
            os.makedirs(data_dir, exist_ok=True)
            
            zip_path = os.path.join(data_dir, "timezones_download.zip")

            _LOGGER.info(f"Downloading timezone data from {TIMEZONE_DATA_URL}")
            
            session = async_get_clientsession(self.hass)
            
            # Stream download to disk instead of loading into RAM
            async with session.get(TIMEZONE_DATA_URL) as response:
                if response.status != 200:
                    _LOGGER.error(f"Failed to download timezone data: HTTP {response.status}")
                    return False
                
                total_size = 0
                with open(zip_path, 'wb') as f:
                    async for chunk in response.content.iter_chunked(8192):
                        f.write(chunk)
                        total_size += len(chunk)
                
                _LOGGER.info(f"Downloaded {total_size / 1024 / 1024:.1f} MB to disk")

            # Get filter prefixes for selected region
            filter_prefixes = REGION_TIMEZONE_PREFIXES.get(self.region_filter)

            # Extract and filter in executor to avoid blocking
            def extract_filter_and_save():
                feature_count = 0
                
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    # Find the geojson file
                    geojson_files = [f for f in zf.namelist() if f.endswith('.geojson') or f.endswith('.json')]
                    if not geojson_files:
                        raise ValueError("No GeoJSON file found in zip archive")
                    
                    geojson_name = geojson_files[0]
                    _LOGGER.info(f"Processing {geojson_name}")
                    
                    # Extract to temp file for streaming parse
                    extracted_path = os.path.join(data_dir, "timezones_temp.geojson")
                    with zf.open(geojson_name) as src, open(extracted_path, 'wb') as dst:
                        # Stream extraction in chunks
                        while True:
                            chunk = src.read(65536)
                            if not chunk:
                                break
                            dst.write(chunk)
                
                # Now process the extracted file with streaming JSON if available
                extracted_path = os.path.join(data_dir, "timezones_temp.geojson")
                
                try:
                    # Try to use ijson for memory-efficient parsing
                    import ijson
                    _LOGGER.debug("Using ijson for memory-efficient parsing")
                    
                    filtered_features = []
                    original_count = 0
                    
                    with open(extracted_path, 'rb') as f:
                        for feature in ijson.items(f, 'features.item'):
                            original_count += 1
                            tz_id = feature.get('properties', {}).get('tzid', '')
                            
                            # Apply filter
                            if filter_prefixes is None:
                                # No filter - include all
                                filtered_features.append(feature)
                            else:
                                for prefix in filter_prefixes:
                                    if prefix.endswith('/'):
                                        if tz_id.startswith(prefix):
                                            filtered_features.append(feature)
                                            break
                                    else:
                                        if tz_id == prefix or tz_id.startswith(prefix + '/'):
                                            filtered_features.append(feature)
                                            break
                    
                    if filter_prefixes is not None:
                        _LOGGER.info(f"Filtered timezones: {original_count} -> {len(filtered_features)} (region: {self.region_filter})")
                    
                    # Write filtered output - use custom encoder for ijson's Decimal objects
                    class DecimalEncoder(json.JSONEncoder):
                        def default(self, obj):
                            if isinstance(obj, Decimal):
                                return float(obj)
                            return super().default(obj)
                    
                    with open(self.timezone_data_path, 'w') as f:
                        json.dump({"type": "FeatureCollection", "features": filtered_features}, f, cls=DecimalEncoder)
                    
                    feature_count = len(filtered_features)
                    
                except ImportError:
                    # Fallback to standard json if ijson not available
                    _LOGGER.debug("ijson not available, using standard JSON parsing")
                    
                    with open(extracted_path, 'r') as f:
                        data = json.load(f)
                    
                    original_count = len(data.get('features', []))
                    
                    if filter_prefixes is not None:
                        filtered_features = []
                        for feature in data.get('features', []):
                            tz_id = feature.get('properties', {}).get('tzid', '')
                            
                            for prefix in filter_prefixes:
                                if prefix.endswith('/'):
                                    if tz_id.startswith(prefix):
                                        filtered_features.append(feature)
                                        break
                                else:
                                    if tz_id == prefix or tz_id.startswith(prefix + '/'):
                                        filtered_features.append(feature)
                                        break
                        
                        data['features'] = filtered_features
                        _LOGGER.info(f"Filtered timezones: {original_count} -> {len(filtered_features)} (region: {self.region_filter})")
                    
                    with open(self.timezone_data_path, 'w') as f:
                        json.dump(data, f)
                    
                    feature_count = len(data.get('features', []))
                    
                    # Free memory
                    del data
                
                # Clean up temp files
                try:
                    os.remove(extracted_path)
                except Exception:
                    pass
                    
                return feature_count
            
            feature_count = await self.hass.async_add_executor_job(extract_filter_and_save)
            
            # Clean up downloaded zip
            try:
                os.remove(zip_path)
            except Exception:
                pass
                
            _LOGGER.info(f"Saved timezone data with {feature_count} boundaries to {self.timezone_data_path}")
            return True

        except Exception as e:
            _LOGGER.error(f"Failed to download timezone data: {e}")
            return False

    async def async_load_timezone_data(self) -> bool:
        """Load timezone boundary polygons from GeoJSON file with memory-efficient streaming."""
        if not SHAPELY_AVAILABLE:
            _LOGGER.error("Cannot load timezone data - shapely not available")
            return False

        # Auto-download if file doesn't exist
        if not os.path.exists(self.timezone_data_path):
            _LOGGER.info(f"Timezone data not found at {self.timezone_data_path}, downloading...")
            if not await self._async_download_timezone_data():
                return False

        def load_data():
            """Load data in executor with streaming JSON if available."""
            polygons = {}
            
            try:
                # Try to use ijson for memory-efficient streaming parse
                import ijson
                _LOGGER.debug("Using ijson for memory-efficient loading")
                
                with open(self.timezone_data_path, 'rb') as f:
                    for feature in ijson.items(f, 'features.item'):
                        tz_id = feature.get('properties', {}).get('tzid')
                        if tz_id and feature.get('geometry'):
                            try:
                                geom = shape(feature['geometry'])
                                if geom.is_valid:
                                    polygons[tz_id] = geom
                                else:
                                    geom = geom.buffer(0)
                                    if geom.is_valid:
                                        polygons[tz_id] = geom
                            except Exception as e:
                                _LOGGER.warning(f"Failed to load geometry for {tz_id}: {e}")
                        
                        # Allow feature dict to be garbage collected
                        del feature
                        
            except ImportError:
                # Fallback to standard json
                _LOGGER.debug("ijson not available, using standard JSON loading")
                
                with open(self.timezone_data_path, 'r') as f:
                    data = json.load(f)

                for feature in data.get('features', []):
                    tz_id = feature.get('properties', {}).get('tzid')
                    if tz_id and feature.get('geometry'):
                        try:
                            geom = shape(feature['geometry'])
                            if geom.is_valid:
                                polygons[tz_id] = geom
                            else:
                                geom = geom.buffer(0)
                                if geom.is_valid:
                                    polygons[tz_id] = geom
                        except Exception as e:
                            _LOGGER.warning(f"Failed to load geometry for {tz_id}: {e}")
                
                # Free memory from the raw JSON data
                del data

            return polygons

        def build_spatial_index(polygons):
            """Build STRtree spatial index for O(log N) queries."""
            tz_index = list(polygons.keys())
            geometries = [polygons[tz_id] for tz_id in tz_index]
            spatial_tree = STRtree(geometries)
            return tz_index, spatial_tree

        try:
            _LOGGER.info(f"Loading timezone data from {self.timezone_data_path}")
            self._tz_polygons = await self.hass.async_add_executor_job(load_data)
            _LOGGER.info(f"Loaded {len(self._tz_polygons)} timezone boundaries")
            
            # Build spatial index
            _LOGGER.debug("Building spatial index...")
            self._tz_index, self._spatial_tree = await self.hass.async_add_executor_job(
                build_spatial_index, self._tz_polygons
            )
            _LOGGER.info(f"Built spatial index for {len(self._tz_index)} timezones")
            
            return True
        except Exception as e:
            _LOGGER.error(f"Failed to load timezone data: {e}")
            return False

    async def async_start(self) -> None:
        """Start the coordinator."""
        self._running = True
        # Do initial update
        await self.async_update()

    async def async_stop(self) -> None:
        """Stop the coordinator."""
        self._running = False
        if self._cancel_scheduled:
            self._cancel_scheduled()
            self._cancel_scheduled = None

    async def async_force_update(self) -> None:
        """Force an immediate update."""
        if self._cancel_scheduled:
            self._cancel_scheduled()
            self._cancel_scheduled = None
        await self.async_update()

    async def async_update(self) -> None:
        """Perform timezone check and schedule next update."""
        if not self._running:
            return

        if not self._tz_polygons:
            _LOGGER.warning("No timezone data loaded")
            self._schedule_next_update(self.max_interval)
            return

        # Get GPS state
        gps_state = self.hass.states.get(self.gps_entity)
        if gps_state is None or gps_state.state == "unavailable":
            _LOGGER.warning(f"GPS entity {self.gps_entity} not available")
            self._schedule_next_update(self.max_interval)
            return

        # Extract coordinates and movement data
        attrs = gps_state.attributes
        lat = attrs.get("latitude") or attrs.get("Latitude")
        lon = attrs.get("longitude") or attrs.get("Longitude")
        speed = attrs.get("speed") or attrs.get("Speed") or 0
        heading = attrs.get("heading") or attrs.get("Heading") or attrs.get("course") or 0

        if lat is None or lon is None:
            _LOGGER.warning(f"GPS entity {self.gps_entity} missing coordinates")
            self._schedule_next_update(self.max_interval)
            return

        lat = float(lat)
        lon = float(lon)
        speed = float(speed) if speed else 0
        heading = float(heading) if heading else 0

        # Update stored GPS data
        self.data.latitude = lat
        self.data.longitude = lon
        self.data.speed = speed
        self.data.heading = heading
        self.data.last_update = datetime.now()

        # Find timezone at current location
        detected_tz = await self.hass.async_add_executor_job(
            self._find_timezone_at_point, lat, lon
        )

        if detected_tz is None:
            _LOGGER.warning(f"Could not determine timezone at ({lat}, {lon})")
            self._schedule_next_update(300)
            return

        self.data.detected_timezone = detected_tz

        # Calculate distances
        edge_distance, nearest_tz = await self.hass.async_add_executor_job(
            self._calculate_distance_to_boundary, lat, lon, detected_tz
        )
        
        self.data.nearest_other_timezone = nearest_tz
        
        if speed > SPEED_STOPPED:
            heading_distance = await self.hass.async_add_executor_job(
                self._calculate_distance_along_heading, lat, lon, heading, detected_tz
            )
        else:
            heading_distance = float('inf')

        effective_distance = min(edge_distance, heading_distance)

        self.data.edge_distance = edge_distance
        self.data.heading_distance = heading_distance
        self.data.effective_distance = effective_distance

        # Calculate interval
        interval = self._calculate_check_interval(effective_distance, speed)
        self.data.check_interval = interval

        # Initialize current timezone if not set
        if self.data.current_timezone is None:
            self.data.current_timezone = detected_tz
            # Check if HA's timezone differs
            ha_tz = self.hass.config.time_zone
            if ha_tz != detected_tz:
                _LOGGER.info(f"Initial timezone mismatch - HA has {ha_tz}, GPS shows {detected_tz}")
                await self._update_ha_timezone(detected_tz)

        # Handle timezone changes with hysteresis
        if detected_tz != self.data.current_timezone:
            if detected_tz == self.data.pending_timezone:
                self.data.pending_count += 1
                if self.data.pending_count >= self.hysteresis_count:
                    # Confirmed timezone change
                    old_tz = self.data.current_timezone
                    if await self._update_ha_timezone(detected_tz):
                        _LOGGER.info(f"Timezone changed from {old_tz} to {detected_tz}")
                    self.data.pending_timezone = None
                    self.data.pending_count = 0
                else:
                    # Waiting for confirmation
                    interval = min(interval, 30)
            else:
                # New pending timezone
                self.data.pending_timezone = detected_tz
                self.data.pending_count = 1
                interval = min(interval, 30)
        else:
            # Still in same timezone
            self.data.pending_timezone = None
            self.data.pending_count = 0

        _LOGGER.debug(
            f"Timezone check: tz={self.data.current_timezone}, "
            f"dist={effective_distance:.1f}mi, speed={speed:.0f}mph, "
            f"interval={interval}s"
        )

        # Notify listeners
        self._notify_listeners()

        # Schedule next update
        self._schedule_next_update(interval)

    def _schedule_next_update(self, interval: int) -> None:
        """Schedule the next update."""
        if self._cancel_scheduled:
            self._cancel_scheduled()

        @callback
        def _scheduled_update(_now):
            self.hass.async_create_task(self.async_update())

        self._cancel_scheduled = async_call_later(
            self.hass, interval, _scheduled_update
        )

    def _find_timezone_at_point(self, lat: float, lon: float) -> str | None:
        """Find which timezone polygon contains the given point using spatial index."""
        if not self._tz_polygons or not self._spatial_tree:
            return None

        point = Point(lon, lat)

        # Use STRtree.query to find candidate polygons that might contain the point
        # This is O(log N) instead of O(N)
        candidate_indices = self._spatial_tree.query(point)
        
        for idx in candidate_indices:
            tz_id = self._tz_index[idx]
            polygon = self._tz_polygons[tz_id]
            try:
                if polygon.contains(point):
                    return tz_id
            except Exception:
                continue

        # If no polygon contains the point, find the nearest one using spatial index
        # query_nearest returns indices of nearest geometries
        try:
            nearest_idx = self._spatial_tree.nearest(point)
            if nearest_idx is not None:
                return self._tz_index[nearest_idx]
        except Exception:
            pass
        
        return None

    def _calculate_distance_to_boundary(self, lat: float, lon: float, tz_id: str) -> tuple[float, str | None]:
        """
        Calculate distance from point to nearest timezone boundary that leads to a different timezone.
        
        Uses STRtree spatial index for O(log N) nearest neighbor queries.
        Ignores coastal boundaries (edges where the other side is ocean/no timezone).
        
        Returns: (distance_in_miles, nearest_timezone_id)
        """
        if not self._tz_polygons or not self._spatial_tree or tz_id not in self._tz_polygons:
            return float('inf'), None

        point = Point(lon, lat)

        try:
            # Use query_nearest to get the k nearest polygons, then filter out current timezone
            # We query for more than we need since one of them will be our current timezone
            k_nearest = min(10, len(self._tz_index))
            nearest_indices = self._spatial_tree.query_nearest(point, k=k_nearest, return_distance=False)
            
            min_distance = float('inf')
            nearest_tz = None
            
            for idx in nearest_indices:
                other_tz_id = self._tz_index[idx]
                if other_tz_id == tz_id:
                    continue
                
                try:
                    other_polygon = self._tz_polygons[other_tz_id]
                    nearest_pt = nearest_points(point, other_polygon)[1]
                    dist_miles = self._haversine_distance(lat, lon, nearest_pt.y, nearest_pt.x)
                    
                    if dist_miles < min_distance:
                        min_distance = dist_miles
                        nearest_tz = other_tz_id
                        
                except Exception:
                    continue
            
            return min_distance, nearest_tz

        except Exception as e:
            _LOGGER.warning(f"Error calculating distance: {e}")
            return float('inf'), None

    def _calculate_distance_along_heading(
        self, lat: float, lon: float, heading: float, tz_id: str, max_distance: float = 200
    ) -> float:
        """
        Calculate distance to timezone boundary along current heading.
        
        Only returns a distance if crossing would lead to a different timezone,
        not if it would lead to ocean/no timezone.
        """
        if not self._tz_polygons or tz_id not in self._tz_polygons:
            return float('inf')

        polygon = self._tz_polygons[tz_id]

        try:
            for dist in [0.5, 1, 2, 5, 10, 20, 50, 100, 150, 200]:
                if dist > max_distance:
                    break

                new_lat, new_lon = self._project_point(lat, lon, heading, dist)
                test_point = Point(new_lon, new_lat)
                
                if not polygon.contains(test_point):
                    # We've left our current timezone - check what's on the other side
                    other_tz = self._find_timezone_at_point(new_lat, new_lon)
                    
                    if other_tz is not None and other_tz != tz_id:
                        # There's a different timezone here - this is a real boundary
                        # Binary search for precise crossing
                        low, high = 0, dist
                        for _ in range(10):
                            mid = (low + high) / 2
                            mid_lat, mid_lon = self._project_point(lat, lon, heading, mid)
                            if polygon.contains(Point(mid_lon, mid_lat)):
                                low = mid
                            else:
                                high = mid
                        return (low + high) / 2
                    # else: it's ocean or same timezone (multipolygon gap) - keep looking

            return max_distance

        except Exception as e:
            _LOGGER.warning(f"Error calculating heading distance: {e}")
            return float('inf')

    def _project_point(self, lat: float, lon: float, heading: float, distance_miles: float) -> tuple[float, float]:
        """Project a point along a heading for a given distance using spherical Earth model."""
        dist_km = distance_miles * 1.60934
        heading_rad = math.radians(heading)
        R = 6371  # Earth radius in km

        lat_rad = math.radians(lat)
        new_lat_rad = math.asin(
            math.sin(lat_rad) * math.cos(dist_km / R) +
            math.cos(lat_rad) * math.sin(dist_km / R) * math.cos(heading_rad)
        )
        new_lon_rad = math.radians(lon) + math.atan2(
            math.sin(heading_rad) * math.sin(dist_km / R) * math.cos(lat_rad),
            math.cos(dist_km / R) - math.sin(lat_rad) * math.sin(new_lat_rad)
        )
        return math.degrees(new_lat_rad), math.degrees(new_lon_rad)

    def _haversine_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance between two points in miles using Haversine formula."""
        lat1_rad, lat2_rad = math.radians(lat1), math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)

        a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad)*math.cos(lat2_rad)*math.sin(delta_lon/2)**2
        return EARTH_RADIUS_MILES * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    def _calculate_check_interval(self, distance: float, speed: float) -> int:
        """Calculate polling interval based on distance and speed."""
        # Distance factor
        if distance < DISTANCE_VERY_CLOSE:
            dist_factor = 0.02
        elif distance < DISTANCE_CLOSE:
            dist_factor = 0.08
        elif distance < DISTANCE_MEDIUM:
            dist_factor = 0.25
        elif distance < DISTANCE_FAR:
            dist_factor = 0.5
        else:
            dist_factor = 1.0

        # Speed factor
        if speed < SPEED_STOPPED:
            speed_factor = 1.0
        elif speed < SPEED_SLOW:
            speed_factor = 0.8
        elif speed < SPEED_FAST:
            speed_factor = 0.5
        else:
            speed_factor = 0.2

        # Combine
        combined = min(dist_factor, speed_factor * 0.7 + dist_factor * 0.3)

        # Special cases
        if distance < DISTANCE_VERY_CLOSE and speed > SPEED_STOPPED:
            combined = 0.01
        if distance < DISTANCE_CLOSE and speed > SPEED_FAST:
            combined = 0.02

        interval = self.min_interval + (self.max_interval - self.min_interval) * combined

        # Cap by ETA
        if speed > SPEED_STOPPED and distance < float('inf'):
            eta_seconds = (distance / speed) * 3600
            interval = min(interval, max(self.min_interval, eta_seconds / 4))

        return max(self.min_interval, min(self.max_interval, int(interval)))

    async def _update_ha_timezone(self, new_timezone: str) -> bool:
        """Update Home Assistant's timezone setting."""
        try:
            await self.hass.config.async_set_time_zone(new_timezone)
            self.data.current_timezone = new_timezone
            _LOGGER.info(f"Updated Home Assistant timezone to {new_timezone}")
            return True
        except Exception as e:
            _LOGGER.error(f"Failed to update timezone: {e}")
            return False

    def get_distance_category(self) -> str:
        """Get human-readable distance category."""
        dist = self.data.effective_distance
        if dist < DISTANCE_VERY_CLOSE:
            return "very_close"
        elif dist < DISTANCE_CLOSE:
            return "close"
        elif dist < DISTANCE_MEDIUM:
            return "medium"
        elif dist < DISTANCE_FAR:
            return "far"
        return "very_far"

    def get_speed_category(self) -> str:
        """Get human-readable speed category."""
        speed = self.data.speed
        if speed < SPEED_STOPPED:
            return "stopped"
        elif speed < SPEED_SLOW:
            return "slow"
        elif speed < SPEED_FAST:
            return "normal"
        return "fast"
