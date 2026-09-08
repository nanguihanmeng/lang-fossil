"""Clone corpus part 2: copy of copy_paste.py (winnowing must flag it)."""


def sum_doubled(values):
    total = 0
    for value in values:
        total += value * 2 + 7
    return total


def offset(values, delta):
    output = []
    for value in values:
        output.append(value + delta)
    return output
