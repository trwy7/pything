import numpy as np
from PIL import Image
from sklearn.cluster import KMeans
import colorsys

# pyinstaller
import scipy._external.array_api_compat.numpy.fft
import scipy._external.array_api_compat.numpy.linalg


def get_accent(path: str) -> int | None:
    # Convert every pixel to RGB so each pixel has exactly three numeric
    # channels, regardless of whether the source image is grayscale, indexed,
    # or has an alpha channel.
    img = Image.open(path).convert("RGB")

    # Clustering every original pixel is unnecessary and can be expensive for
    # album artwork. Pillow preserves the aspect ratio while shrinking the
    # longest side to at most 100 pixels.
    img.thumbnail((100, 100))

    # KMeans expects one sample per row and one feature per column. Here each
    # row is one RGB pixel and the three columns are red, green, and blue.
    pixels = np.array(img).reshape(-1, 3)
    if len(pixels) == 0:
        return None

    # KMeans cannot create more useful clusters than there are distinct RGB
    # values. This also avoids convergence warnings for flat-color artwork.
    distinct_colors = len(np.unique(pixels, axis=0))
    kmean = KMeans(n_clusters=min(5, distinct_colors), n_init="auto", random_state=0)
    kmean.fit(pixels)

    # Each cluster center is a representative RGB color for part of the
    # artwork. The labels identify which cluster owns each original pixel.
    colors = kmean.cluster_centers_

    # Count the pixels assigned to each cluster, then convert those counts to
    # proportions. A tiny, vivid cluster is often an edge or isolated detail,
    # so cluster coverage must affect the final accent score.
    counts = np.bincount(kmean.labels_, minlength=len(colors))
    weights = counts / len(pixels)

    # No candidate has been selected yet. None remains the correct result if
    # every representative color is gray or too close to black or white.
    accent = None
    best_score = -1.0
    for color, weight in zip(colors, weights):
        # Normalize RGB from the 0-255 range to the 0-1 range expected by
        # colorsys.rgb_to_hls. HLS returns hue, lightness, and saturation.
        r, g, b = color / 255.0
        h, l, s = colorsys.rgb_to_hls(r, g, b)

        # Gray colors do not provide a useful hue. Very dark or very light
        # colors are also poor accents because their hue is hard to perceive.
        if s < 0.12 or l < 0.08 or l > 0.92:
            continue

        # Saturation rewards vivid colors. Square-root weighting gives the
        # dominant colors an advantage while keeping smaller meaningful
        # details eligible, without allowing a one-pixel outlier to win on
        # saturation alone.
        score = s * (0.35 + 0.65 * np.sqrt(weight))
        if score > best_score:
            best_score = score
            # The frontend consumes only hue, represented as degrees from
            # red at 0 through the color wheel back to red at 360.
            accent = int(h * 360)
    return accent
