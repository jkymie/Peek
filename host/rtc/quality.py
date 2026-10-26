"""Opções de qualidade (tabela "Qualidade e FPS" do README).

Os nomes que aparecem para quem transmite ficam em ``host.gui.messages``; aqui só
os números.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from aiortc.codecs import h264, vpx


@dataclass(frozen=True)
class Quality:
    preset: str
    height: int | None  # None = tamanho original
    fps: int
    bitrate_kbps: int  # teto de envio de vídeo por espectador


PRESETS: dict[str, Quality] = {
    q.preset: q
    for q in (
        Quality("economica", 480, 30, 1500),
        Quality("equilibrada", 720, 30, 3000),
        Quality("nitida", 1080, 30, 5000),
        Quality("fluida", 720, 60, 4500),
        Quality("maxima", 1080, 60, 8000),
    )
}
DEFAULT_PRESET = "equilibrada"


def resolve_quality(
    preset: str = DEFAULT_PRESET,
    *,
    resolution: str | None = None,
    fps: int | None = None,
    bitrate_kbps: int | None = None,
) -> Quality:
    """Preset com os ajustes individuais (``--resolution``, ``--fps``, ``--bitrate``)."""
    quality = PRESETS[preset]
    if resolution is not None:
        quality = replace(quality, height=None if resolution == "original" else int(resolution))
    if fps is not None:
        quality = replace(quality, fps=fps)
    if bitrate_kbps is not None:
        quality = replace(quality, bitrate_kbps=bitrate_kbps)
    return quality


def scaled_size(width: int, height: int, target_height: int | None) -> tuple[int, int]:
    """Tamanho de envio: nunca maior que o original e sempre par (exigência do YUV 4:2:0)."""
    if target_height is not None and target_height < height:
        # Par mais próximo da largura proporcional (1920x1080 → 854x480).
        width = 2 * round(width * target_height / height / 2)
        height = target_height
    # Sem redução, arredonda para baixo: nunca passa do tamanho real.
    return max(2, width - width % 2), max(2, height - height % 2)


def apply_bitrate_cap(bitrate_kbps: int) -> None:
    """Ajusta o teto de bitrate dos codificadores do aiortc.

    O aiortc limita o VP8 a 1,5 Mbps e o H.264 a 3 Mbps por constantes de módulo,
    lidas a cada ajuste de bitrate. Sem isso, "Nítida" e "Máxima" ficariam presas
    nesses tetos. Vale para todos os espectadores (todos usam a mesma qualidade).

    Depende de detalhe interno do aiortc: revisar ao atualizar a versão fixada.
    """
    bitrate = bitrate_kbps * 1000
    for codec in (vpx, h264):
        codec.MAX_BITRATE = bitrate
        codec.MIN_BITRATE = min(codec.MIN_BITRATE, bitrate)
