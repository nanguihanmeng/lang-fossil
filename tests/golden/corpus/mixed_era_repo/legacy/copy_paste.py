"""Clone corpus part 1: this helper is duplicated across two files."""


def sum_doubled(values):
    total = 0
    for value in values:
        total += value * 2 + 7
    return total


def scale(values, factor):
    result = []
    for value in values:
        result.append(value * factor)
    return result
