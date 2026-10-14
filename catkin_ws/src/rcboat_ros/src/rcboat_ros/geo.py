"""Dependency-free WGS84 latitude/longitude to UTM conversion helpers."""
import math


def latlon_to_utm(latitude, longitude):
    """Return (easting_m, northing_m, zone_label) for a valid WGS84 point."""
    lat = float(latitude)
    lon = float(longitude)
    if not (-80.0 <= lat <= 84.0 and -180.0 <= lon <= 180.0):
        raise ValueError("UTM supports latitude -80..84 and longitude -180..180")
    zone = min(60, max(1, int((lon + 180.0) // 6.0) + 1))
    # Norway and Svalbard special zones from the UTM definition.
    if 56.0 <= lat < 64.0 and 3.0 <= lon < 12.0:
        zone = 32
    if 72.0 <= lat < 84.0:
        if 0.0 <= lon < 9.0:
            zone = 31
        elif lon < 21.0:
            zone = 33
        elif lon < 33.0:
            zone = 35
        elif lon < 42.0:
            zone = 37

    a = 6378137.0
    ecc_sq = 0.0066943799901413165
    k0 = 0.9996
    lat_r = math.radians(lat)
    lon_r = math.radians(lon)
    lon_origin = math.radians((zone - 1) * 6 - 180 + 3)
    ecc_prime_sq = ecc_sq / (1.0 - ecc_sq)
    n = a / math.sqrt(1.0 - ecc_sq * math.sin(lat_r) ** 2)
    t = math.tan(lat_r) ** 2
    c = ecc_prime_sq * math.cos(lat_r) ** 2
    aa = math.cos(lat_r) * (lon_r - lon_origin)
    m = a * (
        (1 - ecc_sq / 4 - 3 * ecc_sq ** 2 / 64 - 5 * ecc_sq ** 3 / 256) * lat_r
        - (3 * ecc_sq / 8 + 3 * ecc_sq ** 2 / 32 + 45 * ecc_sq ** 3 / 1024) * math.sin(2 * lat_r)
        + (15 * ecc_sq ** 2 / 256 + 45 * ecc_sq ** 3 / 1024) * math.sin(4 * lat_r)
        - (35 * ecc_sq ** 3 / 3072) * math.sin(6 * lat_r)
    )
    easting = k0 * n * (
        aa + (1 - t + c) * aa ** 3 / 6
        + (5 - 18 * t + t ** 2 + 72 * c - 58 * ecc_prime_sq) * aa ** 5 / 120
    ) + 500000.0
    northing = k0 * (m + n * math.tan(lat_r) * (
        aa ** 2 / 2
        + (5 - t + 9 * c + 4 * c ** 2) * aa ** 4 / 24
        + (61 - 58 * t + t ** 2 + 600 * c - 330 * ecc_prime_sq) * aa ** 6 / 720
    ))
    hemisphere = "N" if lat >= 0 else "S"
    if lat < 0:
        northing += 10000000.0
    return easting, northing, f"{zone}{hemisphere}"


def enrich_waypoints(waypoints):
    """Validate and normalize route points, preserving no synthetic values."""
    result = []
    for index, point in enumerate(waypoints, 1):
        if not isinstance(point, dict):
            raise ValueError("each waypoint must be an object")
        lat = float(point["lat"])
        lon = float(point["lon"])
        easting, northing, zone = latlon_to_utm(lat, lon)
        normalized = dict(point)
        normalized.update(
            waypoint_number=index,
            lat=lat,
            lon=lon,
            utm_easting_m=round(easting, 3),
            utm_northing_m=round(northing, 3),
            utm_zone=zone,
        )
        result.append(normalized)
    return result
