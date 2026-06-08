from __future__ import annotations

DEFAULT_WINDOW = 5
BLOCK_IMAGES = 10  # frames per block (the pattern repeats every block)
WINDOW = 5  # each tooth is visible across this many frames within a block


def num_objects(num_images: int, window: int = DEFAULT_WINDOW) -> int:
    """How many distinct objects span `num_images`, each visible `window` frames."""
    return max(1, num_images - window + 1)


def present_objects(image_index: int, num_images: int, window: int = DEFAULT_WINDOW) -> list[int]:
    """Object numbers visible on image `image_index` (0-based) for a single
    sliding window over `num_images` images. (Used within one block.)"""
    n = num_objects(num_images, window)
    i = image_index + 1  # 1-based
    lo = max(1, i - window + 1)
    hi = min(n, i)
    return list(range(lo, hi + 1)) if lo <= hi else []


TEETH_PER_BLOCK = num_objects(BLOCK_IMAGES, WINDOW)  # 6


def present_local(image_index: int) -> list[int]:
    """Painted (local) tooth numbers visible on a frame. The window slides within
    each 10-frame block, so every block shows the same 1..6 painted pattern."""
    return present_objects(image_index % BLOCK_IMAGES, BLOCK_IMAGES, WINDOW)


def block_offset(image_index: int) -> int:
    """Global tooth-number offset for the block this frame belongs to."""
    return TEETH_PER_BLOCK * (image_index // BLOCK_IMAGES)


def global_tooth(image_index: int, local_tooth: int) -> int:
    """Real (global) tooth number recorded in the CSV for a painted local one."""
    return local_tooth + block_offset(image_index)
