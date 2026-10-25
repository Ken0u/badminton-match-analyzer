"""The single fixed, opt-in spatial recipe for a development experiment."""

import numpy as np

CANVAS = (768, 432)
TILE_SIZE = (512, 288)
ORIGINS = ((0, 0), (256, 0), (0, 144), (256, 144))


def spatial_recipe(layout, input_size):
    """Keep model tensor dimensions distinct from the assembled heatmap canvas."""
    if layout is None:
        return None
    if layout == "full":
        return {
            "layout": "full",
            "canvas_size": list(input_size),
            "model_input_size": list(input_size),
            "tile_origins": [[0, 0]],
            "fusion": "identity",
            "model_calls_per_window": 1,
        }
    if layout != "overlap_2x2" or tuple(input_size) != CANVAS:
        raise ValueError("Only full or overlap_2x2 on a 768x432 canvas is supported")
    return {
        "layout": layout,
        "canvas_size": list(CANVAS),
        "model_input_size": list(TILE_SIZE),
        "tile_origins": [list(origin) for origin in ORIGINS],
        "fusion": "pixelwise maximum before temporal ensemble",
        "model_calls_per_window": len(ORIGINS),
    }


def predict_tiles(images, predict):
    """Crop matching background/sequence tensors; fuse before temporal averaging.

    Source RGB and the source-resolution median background have already been
    resized to the same canvas by the existing adapter. No tile resampling,
    padding, coordinate correction, edge weighting or whole-frame mixture occurs.
    """
    if (
        not isinstance(images, (list, tuple))
        or len(images) < 2
        or any(
            not isinstance(image, np.ndarray)
            or image.shape != (CANVAS[1], CANVAS[0], 3)
            or image.dtype != np.uint8
            for image in images
        )
    ):
        raise ValueError(
            "Tiles require matching uint8 RGB background/sequence canvases"
        )
    width, height = TILE_SIZE
    fused = np.zeros((len(images) - 1, CANVAS[1], CANVAS[0]), dtype=np.float32)
    for x, y in ORIGINS:
        crops = [image[y : y + height, x : x + width] for image in images]
        heat = predict(crops)
        if (
            not isinstance(heat, np.ndarray)
            or heat.shape != (len(images) - 1, height, width)
            or not np.issubdtype(heat.dtype, np.floating)
            or not np.isfinite(heat).all()
            or np.any(heat < 0)
            or np.any(heat > 1)
        ):
            raise ValueError("Tile predictions must be finite probability heatmaps")
        target = fused[:, y : y + height, x : x + width]
        np.maximum(target, heat, out=target)
    return fused
