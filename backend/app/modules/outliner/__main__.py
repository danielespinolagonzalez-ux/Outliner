"""CLI del outliner (util para verificacion manual):

    python -m app.modules.outliner entrada.pdf salida.pdf [--fallback raster|skip|error]

Imprime el report (ASCII). cp1252: sin Unicode en prints, usar '->'.
"""

import argparse
import json
import sys

from .service import outline_pdf_service


def main(argv=None):
    parser = argparse.ArgumentParser(prog="outliner", description="Texto a curvas")
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--fallback", default="raster",
                        choices=["raster", "skip", "error"])
    parser.add_argument("--raster-dpi", type=int, default=600)
    parser.add_argument("--keep-invisible", action="store_true")
    args = parser.parse_args(argv)

    with open(args.input, "rb") as fh:
        data = fh.read()
    out, report = outline_pdf_service(
        data, fallback=args.fallback, raster_dpi=args.raster_dpi,
        keep_invisible=args.keep_invisible)
    with open(args.output, "wb") as fh:
        fh.write(out)

    print("outliner -> %s (%d bytes)" % (args.output, len(out)))
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
