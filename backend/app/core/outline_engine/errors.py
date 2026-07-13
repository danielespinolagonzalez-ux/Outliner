"""Excepciones tipadas del motor outliner. cp1252: ASCII, usar '->'."""


class OutlineError(Exception):
    """Base de todos los errores del motor."""


class EncryptedPdfError(OutlineError):
    """El PDF esta cifrado y no se dio (o no sirve) la password."""


class CorruptPdfError(OutlineError):
    """El PDF no se puede abrir/parsear."""


class UnsupportedContentError(OutlineError):
    """Una pagina no es convertible y opts.fallback == 'error'.

    Lleva el indice de pagina (0-based) y el motivo, para que el llamador pueda
    reportarlo con precision.
    """

    def __init__(self, page_index: int, reason: str):
        self.page_index = page_index
        self.reason = reason
        super().__init__("pagina %d no convertible: %s" % (page_index, reason))
