"""Informe de conversion del motor outliner.

El endpoint lo devuelve como JSON junto al PDF para que la UI muestre, p.ej.,
"Pagina 3 rasterizada: fuente Type3". cp1252: ASCII, usar '->'.
"""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class PageReport:
    index: int                              # 0-based
    outlined: bool                          # texto convertido a curvas en esta pagina
    outlined_glyphs: int = 0                # glifos emitidos como paths
    fallback: str = ""                      # "" | "raster" | "skip"
    reason: str = ""                        # motivo si fallback/skip
    removed_fonts: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "index": self.index,
            "outlined": self.outlined,
            "outlined_glyphs": self.outlined_glyphs,
            "fallback": self.fallback,
            "reason": self.reason,
            "removed_fonts": list(self.removed_fonts),
            "warnings": list(self.warnings),
        }


@dataclass
class OutlineReport:
    engine: str = "internal"
    pages: List[PageReport] = field(default_factory=list)

    def add(self, page: PageReport) -> None:
        self.pages.append(page)

    @property
    def total_outlined_glyphs(self) -> int:
        return sum(p.outlined_glyphs for p in self.pages)

    @property
    def any_fallback(self) -> bool:
        return any(p.fallback for p in self.pages)

    @property
    def fallback_pages(self) -> List[int]:
        return [p.index for p in self.pages if p.fallback]

    @property
    def all_warnings(self) -> List[str]:
        out: List[str] = []
        for p in self.pages:
            for w in p.warnings:
                out.append("p%d: %s" % (p.index, w))
        return out

    def to_dict(self) -> Dict:
        return {
            "engine": self.engine,
            "pages": [p.to_dict() for p in self.pages],
            "total_outlined_glyphs": self.total_outlined_glyphs,
            "any_fallback": self.any_fallback,
            "fallback_pages": self.fallback_pages,
            "warnings": self.all_warnings,
        }
