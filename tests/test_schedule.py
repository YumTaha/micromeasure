from __future__ import annotations

from micromeasure.services.schedule import (
    global_tooth,
    num_objects,
    present_local,
    present_objects,
)


def main() -> None:
    # the example: window 5, 10 images -> 6 teeth
    assert num_objects(10, 5) == 6
    expected = {
        0: [1],
        1: [1, 2],
        2: [1, 2, 3],
        3: [1, 2, 3, 4],
        4: [1, 2, 3, 4, 5],
        5: [2, 3, 4, 5, 6],
        6: [3, 4, 5, 6],
        7: [4, 5, 6],
        8: [5, 6],
        9: [6],
    }
    for idx, want in expected.items():
        got = present_objects(idx, 10, 5)
        assert got == want, (idx, got, want)

    # each tooth appears in exactly `window` images
    counts = {}
    for idx in range(10):
        for t in present_objects(idx, 10, 5):
            counts[t] = counts.get(t, 0) + 1
    assert all(c == 5 for c in counts.values()), counts

    # block-periodic local pattern (painted 1..6 every 10 frames)
    assert present_local(0) == [1]
    assert present_local(5) == [2, 3, 4, 5, 6]
    assert present_local(9) == [6]
    assert present_local(10) == [1]  # next block repeats the painted pattern
    assert present_local(15) == [2, 3, 4, 5, 6]
    assert present_local(39) == [6]

    # global numbering: block b -> teeth 6b+1 .. 6b+6
    assert global_tooth(0, 1) == 1
    assert global_tooth(5, 6) == 6
    assert global_tooth(10, 1) == 7  # frame 11, painted 1 -> real 7
    assert global_tooth(15, 2) == 8  # frame 16, painted 2 -> real 8
    assert global_tooth(30, 1) == 19  # frame 31 -> block 3
    assert global_tooth(39, 6) == 24  # frame 40, painted 6 -> real 24

    print("schedule: all checks passed")


if __name__ == "__main__":
    main()
