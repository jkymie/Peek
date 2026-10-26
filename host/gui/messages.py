"""Todos os textos que quem transmite vê, em linguagem do dia a dia.

Regra do projeto: nada de termos técnicos ("bitrate", "WebRTC", "tunnel", "porta"...).
Toda mensagem de erro diz o que fazer.
"""

from __future__ import annotations

from host.session import ErrorCode

QUALITY_LABELS: dict[str, tuple[str, str]] = {
    # preset: (nome, frase curta)
    "economica": ("Econômica", "Para internet mais fraca ou muitas pessoas assistindo"),
    "equilibrada": ("Equilibrada", "Boa para quase tudo"),
    "nitida": ("Nítida", "Para filmes, séries e textos"),
    "fluida": ("Fluida", "Para jogos com bastante movimento"),
    "maxima": ("Máxima", "Para PCs potentes com internet rápida"),
}

ERRORS: dict[ErrorCode, str] = {
    ErrorCode.CAPTURE_FAILED: (
        "Não foi possível mostrar o que você escolheu. Escolha outra tela ou janela e tente "
        "novamente."
    ),
    ErrorCode.NO_FRAMES: (
        "A janela escolhida não está aparecendo. Se ela estiver minimizada, abra-a e tente "
        "novamente."
    ),
    ErrorCode.SOURCE_CLOSED: (
        "A janela que você estava mostrando foi fechada. Escolha outra para continuar."
    ),
    ErrorCode.SERVER_FAILED: (
        "Não foi possível começar a transmissão. Feche outras cópias do Peek que estejam "
        "abertas e tente novamente."
    ),
    ErrorCode.UNEXPECTED: (
        "Algo deu errado e a transmissão parou. Tente novamente. Se continuar acontecendo, "
        "reinicie o Peek."
    ),
}


def error_message(code: ErrorCode) -> str:
    return ERRORS.get(code, ERRORS[ErrorCode.UNEXPECTED])
