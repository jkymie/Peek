"""Todos os textos que quem transmite vê, em linguagem do dia a dia.

Regra do projeto: nada de termos técnicos ("bitrate", "WebRTC", "tunnel", "porta"...).
Toda mensagem de erro diz o que fazer.

Pela regra 5 do README, ao lado do nome da qualidade aparecem a resolução e o FPS
("1080p · 30 fps"), gerados por :func:`quality_details`. O nome do dia a dia continua
sendo o principal; números de envio ("kbps") nunca aparecem.

A interface da janela (React, em ``ui/``) recebe estes textos prontos por
:func:`ui_texts`; ela não tem textos próprios.
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
    ErrorCode.TUNNEL_FAILED: (
        "Não foi possível criar o link. Verifique sua conexão com a internet e tente novamente."
    ),
    ErrorCode.TUNNEL_LOST: (
        "O link parou de funcionar e a transmissão foi encerrada. Verifique sua conexão com a "
        "internet e comece de novo."
    ),
    ErrorCode.UNEXPECTED: (
        "Algo deu errado e a transmissão parou. Tente novamente. Se continuar acontecendo, "
        "reinicie o Peek."
    ),
}


def error_message(code: ErrorCode) -> str:
    return ERRORS.get(code, ERRORS[ErrorCode.UNEXPECTED])


def quality_details(height: int | None, fps: int) -> str:
    """Resolução e FPS ao lado do nome da qualidade, ex.: "1080p · 30 fps"."""
    resolution = f"{height}p" if height else "Original"
    return f"{resolution} · {fps} fps"


# --- Janela principal ----------------------------------------------------------

APP_NAME = "Peek"

CHOOSE_TITLE = "O que você quer mostrar?"
REFRESH = "Atualizar lista"
NO_SOURCES = "Nenhuma tela ou janela encontrada. Clique em “Atualizar lista”."
SCREEN_ITEM = "Tela inteira"
SCREEN_ITEM_NUMBERED = "Tela inteira {n}"
SCREEN_PRIMARY = "principal"
WINDOW_MINIMIZED = "minimizada"
SCREENS_GROUP = "Telas"
WINDOWS_GROUP = "Janelas"
FULL_SCREEN_REMINDER = (
    "Lembrete: tudo o que aparecer na tela, incluindo notificações, será visto por quem "
    "estiver assistindo."
)
QUALITY_TITLE = "Qualidade"
START = "Começar a transmitir"

PREPARING = "Preparando a transmissão…"

LIVE_TITLE = "Você está transmitindo!"
LIVE_BADGE = "Ao vivo"
LIVE_SOURCE = "Mostrando: {name}"
LINK_TITLE = "Link para assistir"
COPY_LINK = "Copiar link"
LINK_COPIED = "Link copiado!"
SHARE_HINT = "Mande o link para seus amigos no chat do Discord."
# Só no modo de desenvolvimento sem link público (--no-tunnel).
LOCAL_NETWORK_HINT = (
    "Por enquanto, o link só funciona para quem estiver na mesma rede (Wi-Fi) que você."
)
STOP = "Parar"

SOUND_FAILED = (
    "Não foi possível incluir o som. Seus amigos veem a imagem, mas não ouvem nada. "
    "Para tentar de novo, pare e comece a transmissão outra vez."
)

QUALITY_LIVE_HINT = "A troca vale na hora para quem está assistindo."
QUALITY_CHANGED = "Qualidade trocada para {name}."
QUALITY_FAILED = "Não foi possível trocar a qualidade. A transmissão continua como estava."

SWITCH_SOURCE = "Trocar tela"
SWITCH_TITLE = "O que você quer mostrar agora?"
SWITCH_CONFIRM = "Mostrar esta"
SWITCHING = "Trocando…"
CANCEL = "Cancelar"
SOURCE_SWITCHED = "Agora você está mostrando: {name}"
SWITCH_FAILED = (
    "Não foi possível mostrar o que você escolheu. A transmissão continua mostrando {name}."
)

ERROR_TITLE = "Ops, algo não deu certo"
TRY_AGAIN = "Tentar novamente"
# "Ver detalhes" é a única parte técnica da janela: fica escondida e serve para pedir ajuda.
ERROR_DETAILS_SHOW = "Ver detalhes do erro"
ERROR_DETAILS_HIDE = "Esconder detalhes"
ERROR_DETAILS_HINT = "Se precisar de ajuda, copie estes detalhes e mande para quem cuida do Peek."
COPY_DETAILS = "Copiar detalhes"
DETAILS_COPIED = "Copiado!"
OPEN_LOG_FOLDER = "Abrir pasta de registros"

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


def ui_texts() -> dict[str, str]:
    """Todos os textos simples deste módulo, para a interface da janela."""
    return {
        name: value
        for name, value in globals().items()
        if name.isupper() and isinstance(value, str)
    }
