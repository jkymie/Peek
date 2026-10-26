import pytest
from aiortc.codecs import h264, vpx

from host.__main__ import QUALITY_PRESETS
from host.rtc.quality import PRESETS, apply_bitrate_cap, scaled_size


def test_cli_choices_match_presets():
    assert set(QUALITY_PRESETS) == set(PRESETS)


@pytest.mark.parametrize(
    ("size", "target", "expected"),
    [
        ((1920, 1080), 720, (1280, 720)),
        ((1920, 1080), 480, (854, 480)),
        ((2560, 1440), 1080, (1920, 1080)),
        ((800, 600), 1080, (800, 600)),  # nunca aumenta
        ((1205, 947), None, (1204, 946)),  # original, mas par
        ((1205, 947), 720, (916, 720)),
    ],
)
def test_scaled_size(size, target, expected):
    assert scaled_size(*size, target) == expected


@pytest.fixture
def restore_codec_limits():
    saved = [(c, c.MAX_BITRATE, c.MIN_BITRATE) for c in (vpx, h264)]
    yield
    for codec, max_bitrate, min_bitrate in saved:
        codec.MAX_BITRATE, codec.MIN_BITRATE = max_bitrate, min_bitrate


@pytest.mark.usefixtures("restore_codec_limits")
def test_bitrate_cap_reaches_aiortc_encoders():
    apply_bitrate_cap(8000)
    encoder = vpx.Vp8Encoder()
    encoder.target_bitrate = 50_000_000
    assert encoder.target_bitrate == 8_000_000

    apply_bitrate_cap(200)  # abaixo do mínimo padrão do aiortc
    encoder.target_bitrate = 50_000_000
    assert encoder.target_bitrate == 200_000
