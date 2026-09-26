from app.geo import haversine_m


def test_zero_distance_for_identical_points():
    assert haversine_m(-6.2, 106.8, -6.2, 106.8) == 0.0


def test_known_distance_jakarta_to_bandung_within_tolerance():
    # Monas (Jakarta) to Gedung Sate (Bandung), real-world distance ~115 km
    distance = haversine_m(-6.1754, 106.8272, -6.9024, 107.6186)
    assert 110_000 < distance < 120_000
