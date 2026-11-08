import colorsys
from datetime import datetime

import numpy as np
from PIL import Image
from skimage import color
from sklearn.cluster import KMeans

from . import app


def get_accent(path: str) -> int | None:
    start_time = datetime.now()
    # 1. Load image and resize to a 50x50 thumbnail.
    # 2,500 pixels is plenty to capture dominant artwork colors while keeping performance fast.
    img = Image.open(path).convert("RGB")
    img = img.resize((50, 50), Image.Resampling.BILINEAR)

    img_np = np.array(img)
    pixels_rgb = img_np.reshape(-1, 3)
    if len(pixels_rgb) == 0:
        return None

    # 2. Convert to LAB color space for perceptually uniform clustering
    pixels_lab = color.rgb2lab(pixels_rgb / 255.0)

    distinct_colors = len(np.unique(pixels_lab, axis=0))
    if distinct_colors == 0:
        return None

    # 3. Increase clusters to 10 to catch small, highly saturated details
    n_clusters = min(10, distinct_colors)
    kmean = KMeans(n_clusters=n_clusters, n_init="auto", random_state=0)
    labels = kmean.fit_predict(pixels_lab)
    cluster_centers_lab = kmean.cluster_centers_

    # Calculate overall population weights
    counts = np.bincount(labels, minlength=n_clusters)
    weights = counts / len(pixels_lab)

    # 4. Extract edge pixels (top, bottom, left, right borders) to calculate edge presence
    top = img_np[0, :, :]
    bottom = img_np[-1, :, :]
    left = img_np[:, 0, :]
    right = img_np[:, -1, :]
    edge_pixels_rgb = np.vstack([top, bottom, left, right])
    edge_pixels_lab = color.rgb2lab(edge_pixels_rgb / 255.0)

    # Assign edge pixels to nearest cluster centers
    edge_labels = kmean.predict(edge_pixels_lab)
    edge_counts = np.bincount(edge_labels, minlength=n_clusters)
    edge_weights = edge_counts / len(edge_pixels_lab)

    # Convert LAB cluster centers back to normalized RGB for colorsys evaluation
    cluster_centers_rgb = color.lab2rgb(cluster_centers_lab)

    # Ideal target parameters for Spotify-style UI accents
    TARGET_SATURATION = 1.0
    TARGET_LIGHTNESS = 0.5

    WEIGHT_SATURATION = 3.0
    WEIGHT_LIGHTNESS = 1.5
    WEIGHT_POPULATION = 1.0
    WEIGHT_EDGE = 2

    accent = None
    best_score = -1.0

    for idx, (rgb_color, weight, edge_weight) in enumerate(
        zip(cluster_centers_rgb, weights, edge_weights)
    ):
        r, g, b = np.clip(rgb_color, 0.0, 1.0)
        h, l, s = colorsys.rgb_to_hls(r, g, b)

        # Filter out extreme grays, darks, or highlights
        if s < 0.12 or l < 0.08 or l > 0.92:
            continue

        # Distance penalty relative to ideal targets
        sat_score = 1.0 - abs(s - TARGET_SATURATION)
        light_score = 1.0 - abs(l - TARGET_LIGHTNESS)
        pop_score = np.sqrt(weight)
        edge_score = np.sqrt(edge_weight)

        # Composite score calculation
        score = (
            (sat_score * WEIGHT_SATURATION)
            + (light_score * WEIGHT_LIGHTNESS)
            + (pop_score * WEIGHT_POPULATION)
            + (edge_score * WEIGHT_EDGE)
        )

        if score > best_score:
            best_score = score
            accent = int(h * 360)

    end_time = datetime.now()
    elapsed_time = (end_time - start_time).total_seconds()
    app.logger.debug("Accent color extraction took %.3f seconds", elapsed_time)
    if elapsed_time > 0.1:
        app.logger.warning(
            "Accent color extraction took %.3f seconds, which is longer than expected. Consider optimizing the image size or processing method.",
            elapsed_time,
        )
    return accent
