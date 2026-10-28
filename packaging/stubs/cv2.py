"""Substituto do OpenCV dentro do Peek.exe.

O ``windows-capture`` importa o ``cv2`` só para ``Frame.save_as_image``, que o Peek
não usa. O OpenCV de verdade tem ~110 MB; sem ele o executável fica bem menor e
abre mais rápido. O ``peek.spec`` coloca esta pasta à frente das bibliotecas.
"""


def __getattr__(name: str):
    # AttributeError (e não outro erro): hasattr() e o inspect contam com ele.
    raise AttributeError(f"OpenCV não está incluído no Peek.exe (cv2.{name})")
