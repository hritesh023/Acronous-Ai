import io, json, base64
from PIL import Image, ImageDraw
import numpy as np
from app import edit_image

img = Image.new("RGB", (200, 200), (200, 200, 200))
d = ImageDraw.Draw(img)
d.rectangle([30, 50, 170, 150], fill=(80, 80, 80))

buf = io.BytesIO()
img.save(buf, format="JPEG", quality=95)
img_bytes = buf.getvalue()

result = edit_image(img_bytes, "make my shirt red")
print("Strategy:", result.get("strategy"))
print("Interpretation:", result.get("interpretation"))

edited_b64 = result.get("edited", "")
edited_bytes = base64.b64decode(edited_b64)
edited_img = Image.open(io.BytesIO(edited_bytes))
pixels = np.array(edited_img)
print("Edited shape:", pixels.shape)
print("Center pixel (shirt area):", pixels[100, 100])
print("Corner pixel (background):", pixels[10, 10])
shirt_pixels = pixels[50:150, 30:170]
print("Mean R: {:.1f}, G: {:.1f}, B: {:.1f}".format(
    np.mean(shirt_pixels[:,:,0]), np.mean(shirt_pixels[:,:,1]), np.mean(shirt_pixels[:,:,2])))
