def cp_to_winrate(cp: int) -> float:
    """
    Convert centipawn score into approximate winrate (0-100%).
    This is a heuristic curve.
    """
    import math
    return 50 + (50 * (2 / (1 + math.exp(-0.004 * cp)) - 1))
