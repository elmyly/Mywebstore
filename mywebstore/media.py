import base64
from io import BytesIO

from flask import url_for


def generate_qr_data_uri(text: str) -> str:
    try:
        import qrcode

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = BytesIO()
        img.save(buf, format="PNG")
        return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"
    except Exception:
        import html

        escaped = html.escape(text)
        svg = (
            "<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200'>"
            "<rect width='100%' height='100%' fill='#eee'/>"
            "<text x='50%' y='50%' dominant-baseline='middle' text-anchor='middle'"
            " font-size='12' fill='#444'>QR: "
            f"{escaped}</text></svg>"
        )
        return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def generate_barcode_svg_data_uri(code_text: str) -> str:
    try:
        import barcode
        from barcode.writer import SVGWriter

        cls = barcode.get_barcode_class("code128")
        bc = cls(code_text, writer=SVGWriter())
        buf = BytesIO()
        bc.write(buf, options={"module_height": 12.0, "font_size": 10, "text_distance": 1})
        return f"data:image/svg+xml;base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"
    except Exception:
        svg = (
            "<svg xmlns='http://www.w3.org/2000/svg' width='280' height='80'>"
            "<rect width='100%' height='100%' fill='#fff' stroke='#000'/>"
            "<text x='50%' y='50%' dominant-baseline='middle' text-anchor='middle'"
            " font-size='18' fill='#111'>ID: "
            f"{code_text}</text></svg>"
        )
        return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")




__all__ = [
    "generate_qr_data_uri",
    "generate_barcode_svg_data_uri",
]
