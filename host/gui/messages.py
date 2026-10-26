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


# --- Janela principal ----------------------------------------------------------

APP_NAME = "Peek"

CHOOSE_TITLE = "O que você quer mostrar?"
REFRESH = "Atualizar lista"
NO_SOURCES = "Nenhuma tela ou janela encontrada. Clique em “Atualizar lista”."
SCREEN_ITEM = "Tela inteira"
SCREEN_ITEM_NUMBERED = "Tela inteira {n}"
SCREEN_PRIMARY = "principal"
WINDOW_MINIMIZED = "minimizada"
FULL_SCREEN_REMINDER = (
    "Lembrete: tudo o que aparecer na tela, incluindo notificações, será visto por quem "
    "estiver assistindo."
)
QUALITY_TITLE = "Qualidade"
START = "Começar a transmitir"

PREPARING = "Preparando a transmissão…"

LIVE_TITLE = "Você está transmitindo!"
LIVE_SOURCE = "Mostrando: {name}"
COPY_LINK = "Copiar link"
LINK_COPIED = "Link copiado!"
SHARE_HINT = "Mande o link para seus amigos no chat do Discord."
# Temporário: até o link público (Fase 3) ficar pronto.
LOCAL_NETWORK_HINT = (
    "Por enquanto, o link só funciona para quem estiver na mesma rede (Wi-Fi) que você."
)
STOP = "Parar"

ERROR_TITLE = "Ops, algo não deu certo"
TRY_AGAIN = "Tentar novamente"

CLOSE_CONFIRM_TITLE = "Parar a transmissão?"
CLOSE_CONFIRM_TEXT = "Se você fechar o Peek, quem está assistindo vai parar de ver a sua tela."
CLOSE_CONFIRM_YES = "Parar e fechar"
CLOSE_CONFIRM_NO = "Continuar transmitindo"


def viewers_text(count: int) -> str:
    if count == 0:
        return "Ninguém assistindo ainda"
    if count == 1:
        return "1 pessoa assistindo"
    return f"{count} pessoas assistindo"
