import numpy as np
from PIL import Image
from sklearn.cluster import KMeans
import colorsys

def get_accent(path: str) -> int | None:
    # commented as much as possible so i hopefully can remember how this works later
    # Load the image
    img = Image.open(path).convert("RGB")
    # make it smaller and easier to process
    img.thumbnail((100,100)) # might need tweaking
    # convert to pixels, no idea how this works
    pixels = np.array(img).reshape(-1, 3)
    # use a model to find dominant colors
    kmean = KMeans(n_clusters=5, n_init='auto')
    kmean.fit(pixels)
    colors = kmean.cluster_centers_
    # convert to hsl, then find most saturated (probably a better way to do this)
    accent = None
    max_sat = -1
    for color in colors:
        r, g, b = color / 255.0
        h, l, s = colorsys.rgb_to_hls(r, g , b)
        if s > max_sat:
            max_sat = s
            accent = int(h * 360)
    return accent