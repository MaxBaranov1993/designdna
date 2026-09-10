"""A usable image fixture for Quality Pass tests that assert delivery acceptance."""
import base64
import copy
import io

from PIL import Image
from test_qualitygate import BASE_IR

QUALITY_IR = copy.deepcopy(BASE_IR)
_buffer = io.BytesIO()
Image.new("RGB", (96, 64), (40, 90, 150)).save(_buffer, "PNG")
next(node for node in QUALITY_IR["tree"] if node["type"] == "hero")["props"]["media"]["src"] = (
    "data:image/png;base64," + base64.b64encode(_buffer.getvalue()).decode())
