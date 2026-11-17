# Third-party notices

This bundle includes Lark Channel SDK 1.4.0, Lark OpenAPI SDK 1.7.5, qrcode 8.2, and their locked runtime dependencies listed in `dependencies.lock.json`. Their original licenses and notices are included in the corresponding `vendor/*.dist-info` directories. The SDK's own license and third-party notices are in `vendor/lark_channel_sdk-1.4.0.dist-info/licenses/`. Native wheels in this bundle target Linux x86-64; they are not portable to other operating systems or architectures.

The registration adapter subclasses `lark_oapi.scene.registration._AsyncFlow` from the pinned Lark OpenAPI SDK 1.7.5 (MIT license), reusing its request, QR option, and response handling. Its polling loop waits for explicit server expiration instead of applying the SDK's local elapsed-time deadline; transient polling network failures retry the same device code. The dependency's original license is preserved in the bundle.
