"""Official app chat entry; QR encoding runs in the isolated dependency worker."""

def chat_entry(app_id):
    """Encode the configured app's fixed official chat entry once per app ID."""
    import base64
    import io
    import qrcode
    from qrcode.image.svg import SvgPathImage
    from urllib.parse import urlencode
    url = 'https://applink.feishu.cn/client/bot/open?' + urlencode({'appId': app_id})
    qr = qrcode.QRCode(box_size=8, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    stream = io.BytesIO()
    qr.make_image(image_factory=SvgPathImage).save(stream)
    return dict(chatUrl=url, chatQrImageSource='data:image/svg+xml;base64,' +
                base64.b64encode(stream.getvalue()).decode('ascii'), chatQrModules=qr.modules_count + 8)

